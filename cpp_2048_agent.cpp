#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <string>
#include <unordered_map>
#include <vector>

using Board = std::uint64_t;

namespace {

constexpr int kSize = 4;
constexpr int kCells = 16;
constexpr double kDeadScore = -1.0e18;

std::array<std::uint16_t, 65536> row_left;
std::array<std::uint16_t, 65536> row_right;
std::array<int, 65536> row_left_reward;
std::array<int, 65536> row_right_reward;
std::array<float, 65536> row_score;
std::array<int, 65536> row_empty;
std::array<bool, 65536> row_can_move;
std::array<double, 16> pow4_table;
std::array<double, 16> pow5_table;

struct MoveResult {
    Board board = 0;
    int reward = 0;
    bool moved = false;
};

struct SearchParams {
    int max_depth = 5;
    int black_depth = 5;
    double probability_cutoff = 0.00008;
    int max_chance_cells = 0;
    int time_ms = 0;
};

struct SearchStats {
    std::uint64_t nodes = 0;
    bool timed_out = false;
};

struct CacheKey {
    Board board;
    int depth;
};

struct CacheKeyHash {
    std::size_t operator()(const CacheKey &key) const {
        std::uint64_t x = key.board ^ (static_cast<std::uint64_t>(key.depth) * 0x9e3779b97f4a7c15ULL);
        x ^= x >> 30;
        x *= 0xbf58476d1ce4e5b9ULL;
        x ^= x >> 27;
        x *= 0x94d049bb133111ebULL;
        x ^= x >> 31;
        return static_cast<std::size_t>(x);
    }
};

bool operator==(const CacheKey &a, const CacheKey &b) {
    return a.board == b.board && a.depth == b.depth;
}

double pow4(int value) {
    return pow4_table[std::clamp(value, 0, 15)];
}

double pow5(int value) {
    return pow5_table[std::clamp(value, 0, 15)];
}

std::uint16_t pack_row(const std::array<int, 4> &cells) {
    std::uint16_t row = 0;
    for (int i = 0; i < 4; ++i) {
        row |= static_cast<std::uint16_t>((cells[i] & 0xF) << (4 * i));
    }
    return row;
}

std::array<int, 4> unpack_row(std::uint16_t row) {
    return {
        static_cast<int>(row & 0xF),
        static_cast<int>((row >> 4) & 0xF),
        static_cast<int>((row >> 8) & 0xF),
        static_cast<int>((row >> 12) & 0xF),
    };
}

std::pair<std::array<int, 4>, int> merge_left(std::array<int, 4> cells) {
    std::array<int, 4> compact{0, 0, 0, 0};
    int compact_count = 0;
    for (int value : cells) {
        if (value != 0) {
            compact[compact_count++] = value;
        }
    }

    std::array<int, 4> out{0, 0, 0, 0};
    int out_count = 0;
    int reward = 0;
    for (int i = 0; i < compact_count;) {
        if (i + 1 < compact_count && compact[i] == compact[i + 1] && compact[i] < 15) {
            int value = compact[i] + 1;
            out[out_count++] = value;
            reward += 1 << value;
            i += 2;
        } else {
            out[out_count++] = compact[i++];
        }
    }
    return {out, reward};
}

float score_row(std::array<int, 4> cells) {
    int empty = 0;
    int merges = 0;
    int previous = 0;
    int counter = 0;
    double sum_power = 0.0;
    std::array<double, 4> powers{};

    for (int i = 0; i < 4; ++i) {
        int value = cells[i];
        powers[i] = pow4(value);
        if (value == 0) {
            ++empty;
            continue;
        }
        sum_power += std::pow(static_cast<double>(value), 3.5);
        if (value == previous) {
            ++counter;
        } else if (counter > 0) {
            merges += 1 + counter;
            counter = 0;
        }
        previous = value;
    }
    if (counter > 0) {
        merges += 1 + counter;
    }

    double mono_left = 0.0;
    double mono_right = 0.0;
    for (int i = 0; i < 3; ++i) {
        double diff = powers[i] - powers[i + 1];
        if (diff > 0) {
            mono_right += diff;
        } else {
            mono_left -= diff;
        }
    }

    return static_cast<float>(
        empty * 420.0 +
        merges * 700.0 -
        std::min(mono_left, mono_right) * 47.0 -
        sum_power * 11.0
    );
}

void init_tables() {
    for (int value = 0; value < 16; ++value) {
        double x = static_cast<double>(value);
        pow4_table[value] = x * x * x * x;
        pow5_table[value] = pow4_table[value] * x;
    }

    for (int row = 0; row < 65536; ++row) {
        auto cells = unpack_row(static_cast<std::uint16_t>(row));
        auto [left_cells, left_reward] = merge_left(cells);
        auto reversed = std::array<int, 4>{cells[3], cells[2], cells[1], cells[0]};
        auto [right_reversed, right_reward] = merge_left(reversed);
        auto right_cells = std::array<int, 4>{right_reversed[3], right_reversed[2], right_reversed[1], right_reversed[0]};

        row_left[row] = pack_row(left_cells);
        row_right[row] = pack_row(right_cells);
        row_left_reward[row] = left_reward;
        row_right_reward[row] = right_reward;
        row_score[row] = score_row(cells);

        int empties = 0;
        bool can_move = false;
        for (int i = 0; i < 4; ++i) {
            if (cells[i] == 0) {
                ++empties;
                can_move = true;
            }
            if (i + 1 < 4 && cells[i] == cells[i + 1] && cells[i] < 15) {
                can_move = true;
            }
        }
        row_empty[row] = empties;
        row_can_move[row] = can_move;
    }
}

int cell(Board board, int index) {
    return static_cast<int>((board >> (4 * index)) & 0xFULL);
}

Board set_cell(Board board, int index, int value) {
    Board mask = 0xFULL << (4 * index);
    board &= ~mask;
    board |= (static_cast<Board>(value & 0xF) << (4 * index));
    return board;
}

MoveResult move_left(Board board) {
    Board next = 0;
    int reward = 0;
    for (int r = 0; r < 4; ++r) {
        std::uint16_t row = static_cast<std::uint16_t>((board >> (16 * r)) & 0xFFFFU);
        next |= static_cast<Board>(row_left[row]) << (16 * r);
        reward += row_left_reward[row];
    }
    return {next, reward, next != board};
}

MoveResult move_right(Board board) {
    Board next = 0;
    int reward = 0;
    for (int r = 0; r < 4; ++r) {
        std::uint16_t row = static_cast<std::uint16_t>((board >> (16 * r)) & 0xFFFFU);
        next |= static_cast<Board>(row_right[row]) << (16 * r);
        reward += row_right_reward[row];
    }
    return {next, reward, next != board};
}

MoveResult move_up(Board board) {
    Board next = 0;
    int reward = 0;
    for (int c = 0; c < 4; ++c) {
        std::uint16_t col = 0;
        for (int r = 0; r < 4; ++r) {
            col |= static_cast<std::uint16_t>(cell(board, r * 4 + c) << (4 * r));
        }
        std::uint16_t moved = row_left[col];
        reward += row_left_reward[col];
        for (int r = 0; r < 4; ++r) {
            next |= static_cast<Board>((moved >> (4 * r)) & 0xF) << (4 * (r * 4 + c));
        }
    }
    return {next, reward, next != board};
}

MoveResult move_down(Board board) {
    Board next = 0;
    int reward = 0;
    for (int c = 0; c < 4; ++c) {
        std::uint16_t col = 0;
        for (int r = 0; r < 4; ++r) {
            col |= static_cast<std::uint16_t>(cell(board, r * 4 + c) << (4 * r));
        }
        std::uint16_t moved = row_right[col];
        reward += row_right_reward[col];
        for (int r = 0; r < 4; ++r) {
            next |= static_cast<Board>((moved >> (4 * r)) & 0xF) << (4 * (r * 4 + c));
        }
    }
    return {next, reward, next != board};
}

MoveResult move_board(Board board, int direction) {
    switch (direction) {
        case 0: return move_up(board);
        case 1: return move_left(board);
        case 2: return move_down(board);
        default: return move_right(board);
    }
}

std::array<MoveResult, 4> all_moves(Board board) {
    return {move_up(board), move_left(board), move_down(board), move_right(board)};
}

int empty_count(Board board) {
    int empties = 0;
    for (int r = 0; r < 4; ++r) {
        std::uint16_t row = static_cast<std::uint16_t>((board >> (16 * r)) & 0xFFFFU);
        empties += row_empty[row];
    }
    return empties;
}

std::vector<int> empty_positions(Board board) {
    std::vector<int> result;
    result.reserve(16);
    for (int i = 0; i < 16; ++i) {
        if (cell(board, i) == 0) {
            result.push_back(i);
        }
    }
    return result;
}

bool has_moves(Board board) {
    for (int r = 0; r < 4; ++r) {
        std::uint16_t row = static_cast<std::uint16_t>((board >> (16 * r)) & 0xFFFFU);
        if (row_can_move[row]) {
            return true;
        }
    }
    for (int c = 0; c < 4; ++c) {
        std::uint16_t col = 0;
        for (int r = 0; r < 4; ++r) {
            col |= static_cast<std::uint16_t>(cell(board, r * 4 + c) << (4 * r));
        }
        if (row_can_move[col]) {
            return true;
        }
    }
    return false;
}

std::pair<int, int> top_two(Board board) {
    int first = 0;
    int second = 0;
    for (int i = 0; i < 16; ++i) {
        int value = cell(board, i);
        if (value >= first) {
            second = first;
            first = value;
        } else if (value > second) {
            second = value;
        }
    }
    return {first, second};
}

std::array<int, 6> top_exponents(Board board) {
    std::array<int, 6> top{};
    for (int i = 0; i < 16; ++i) {
        int value = cell(board, i);
        for (int rank = 0; rank < 6; ++rank) {
            if (value > top[rank]) {
                for (int j = 5; j > rank; --j) {
                    top[j] = top[j - 1];
                }
                top[rank] = value;
                break;
            }
        }
    }
    return top;
}

int count_equal(Board board, int value) {
    int count = 0;
    for (int i = 0; i < 16; ++i) {
        if (cell(board, i) == value) {
            ++count;
        }
    }
    return count;
}

bool has_corner_tile(Board board, int value) {
    static constexpr int corners[4] = {0, 3, 12, 15};
    for (int index : corners) {
        if (cell(board, index) == value) {
            return true;
        }
    }
    return false;
}

int nearest_corner_distance(Board board, int value) {
    static constexpr int corners[4] = {0, 3, 12, 15};
    int best = 6;
    for (int i = 0; i < 16; ++i) {
        if (cell(board, i) != value) {
            continue;
        }
        int row = i / 4;
        int col = i % 4;
        for (int corner : corners) {
            int corner_row = corner / 4;
            int corner_col = corner % 4;
            best = std::min(best, std::abs(row - corner_row) + std::abs(col - corner_col));
        }
    }
    return best == 6 ? 0 : best;
}

double large_merge_priority_score(Board before, Board after) {
    auto before_top = top_exponents(before);
    auto after_top = top_exponents(after);
    int largest = before_top[0];
    if (largest < 10) {
        return 0.0;
    }

    double score = 0.0;
    if (after_top[0] > largest) {
        score += pow5(after_top[0]) * (after_top[0] >= 12 ? 9000000.0 : 3600000.0);
        if (count_equal(before, largest) >= 2) {
            score += pow5(after_top[0]) * 9000000.0;
        }
    }

    if (largest >= 11 &&
        count_equal(before, largest - 1) >= 2 &&
        count_equal(after, largest) > count_equal(before, largest)) {
        score += pow5(largest) * 6200000.0;
    }

    if (largest >= 12 &&
        count_equal(before, largest - 1) >= 2 &&
        count_equal(after, largest) > count_equal(before, largest)) {
        score += pow5(largest) * 4200000.0;
    }

    return score;
}

float line_shape_score(Board board) {
    float score = 0.0f;
    for (int r = 0; r < 4; ++r) {
        std::uint16_t row = static_cast<std::uint16_t>((board >> (16 * r)) & 0xFFFFU);
        score += row_score[row];
    }
    for (int c = 0; c < 4; ++c) {
        std::uint16_t col = 0;
        for (int r = 0; r < 4; ++r) {
            col |= static_cast<std::uint16_t>(cell(board, r * 4 + c) << (4 * r));
        }
        score += row_score[col];
    }
    return score;
}

double eval_board(Board board) {
    if (!has_moves(board)) {
        return kDeadScore;
    }

    double score = static_cast<double>(line_shape_score(board));

    auto [largest, _second] = top_two(board);

    if (largest >= 9) {
        int max_corner_bonus = has_corner_tile(board, largest) ? 1 : 0;
        double power = pow4(largest);
        if (largest >= 11) {
            score += (max_corner_bonus ? 180.0 : -420.0) * power;
        } else {
            score += (max_corner_bonus ? 80.0 : -120.0) * power;
        }
        if (largest >= 11) {
            score -= nearest_corner_distance(board, largest) * power * 420.0;
        }
    }

    return score;
}

int processed_reward(int reward) {
    if (reward < 200) {
        return std::max(0, (reward >> 2) - 10);
    }
    if (reward < 500) {
        return (reward >> 1) - 12;
    }
    if (reward < 1000) {
        return (reward >> 1) + 144;
    }
    if (reward < 2000) {
        return reward + 600;
    }
    return 3000;
}

double milestone_transition_score(Board before, Board after) {
    auto [before_max, _before_second] = top_two(before);
    auto top = top_exponents(after);
    int after_max = top[0];
    if (after_max <= before_max || after_max < 12) {
        return 0.0;
    }

    double scale = pow4(after_max);
    double strength = 1.0;
    int empty_floor = 6;
    int empties = empty_count(after);
    double score = 0.0;

    if (has_corner_tile(after, after_max)) {
        score += scale * 9000.0 * strength;
    } else {
        score -= scale * 32000.0 * strength;
    }

    if (empties > empty_floor) {
        score += scale * (empties - empty_floor) * 1000.0 * strength;
    } else if (empties < empty_floor) {
        score -= scale * (empty_floor - empties) * 6500.0 * strength;
    }

    if (top[1] >= after_max - 2) {
        score += scale * 1800.0 * strength;
    } else {
        score -= scale * (after_max - top[1] - 2) * 4200.0 * strength;
    }

    if (top[2] >= after_max - 3) {
        score += scale * 900.0 * strength;
    } else {
        score -= scale * std::max(0, after_max - top[2] - 3) * 1300.0 * strength;
    }

    return score;
}

bool bad_milestone_merge(Board before, Board after) {
    auto [before_max, _before_second] = top_two(before);
    auto top = top_exponents(after);
    int after_max = top[0];
    if (after_max <= before_max || after_max < 12) {
        return false;
    }
    if (empty_count(after) < 2) {
        return true;
    }
    return false;
}

bool bad_endgame_shape_move(Board before, Board after) {
    (void)before;
    (void)after;
    return false;
}

int max_tile(Board board) {
    int max_exp = 0;
    for (int i = 0; i < 16; ++i) {
        max_exp = std::max(max_exp, cell(board, i));
    }
    return max_exp == 0 ? 0 : (1 << max_exp);
}

std::vector<int> selected_chance_cells(Board board, const std::vector<int> &empty, int limit) {
    if (limit <= 0 || static_cast<int>(empty.size()) <= limit) {
        return empty;
    }

    int largest = top_two(board).first;
    std::vector<std::pair<int, int>> ranked;
    ranked.reserve(empty.size());
    for (int index : empty) {
        int row = index / 4;
        int col = index % 4;
        int neighbor = 0;
        const int deltas[4] = {-4, 4, -1, 1};
        for (int delta : deltas) {
            int n = index + delta;
            if (n < 0 || n >= 16) {
                continue;
            }
            if (delta == -1 && col == 0) {
                continue;
            }
            if (delta == 1 && col == 3) {
                continue;
            }
            neighbor = std::max(neighbor, cell(board, n));
        }
        int edge = (row == 0 || row == 3 || col == 0 || col == 3) ? 1 : 0;
        int priority = neighbor * 16 + edge * 4 + (neighbor >= largest - 2 ? 32 : 0);
        ranked.push_back({priority, index});
    }
    std::sort(ranked.begin(), ranked.end(), [](const auto &a, const auto &b) {
        return a.first > b.first;
    });

    std::vector<int> result;
    result.reserve(limit);
    for (int i = 0; i < limit; ++i) {
        result.push_back(ranked[i].second);
    }
    return result;
}

class Expectimax {
public:
    Expectimax(SearchParams params)
        : params_(params), started_(std::chrono::steady_clock::now()) {}

    int choose(Board board, SearchStats &stats) {
        cache_.clear();
        if (cache_.bucket_count() < 262144) {
            cache_.reserve(262144);
        }
        started_ = std::chrono::steady_clock::now();
        int best_dir = -1;
        double best_score = kDeadScore;

        auto moves = all_moves(board);
        int dynamic_depth = effective_depth(board);
        bool has_safe_milestone_move = false;
        for (const MoveResult &move : moves) {
            if (move.moved && !bad_milestone_merge(board, move.board)) {
                has_safe_milestone_move = true;
                break;
            }
        }
        bool has_endgame_shape_safe_move = false;
        for (const MoveResult &move : moves) {
            if (move.moved && !bad_endgame_shape_move(board, move.board)) {
                has_endgame_shape_safe_move = true;
                break;
            }
        }
        for (int dir = 0; dir < 4; ++dir) {
            if (!moves[dir].moved) {
                continue;
            }
            if (has_safe_milestone_move && bad_milestone_merge(board, moves[dir].board)) {
                continue;
            }
            if (has_endgame_shape_safe_move && bad_endgame_shape_move(board, moves[dir].board)) {
                continue;
            }
            double value = processed_reward(moves[dir].reward) +
                large_merge_priority_score(board, moves[dir].board) +
                milestone_transition_score(board, moves[dir].board) +
                chance_node(moves[dir].board, dynamic_depth, 1.0, stats);
            if (best_dir < 0 || value > best_score) {
                best_score = value;
                best_dir = dir;
            }
        }
        if (best_dir < 0) {
            for (int dir = 0; dir < 4; ++dir) {
                if (!moves[dir].moved) {
                    continue;
                }
                double value = processed_reward(moves[dir].reward) +
                    large_merge_priority_score(board, moves[dir].board) +
                    milestone_transition_score(board, moves[dir].board) +
                    chance_node(moves[dir].board, dynamic_depth, 1.0, stats);
                if (best_dir < 0 || value > best_score) {
                    best_score = value;
                    best_dir = dir;
                }
            }
        }
        return best_dir;
    }

private:
    int effective_depth(Board board) const {
        auto [largest, _second] = top_two(board);
        int empties = empty_count(board);
        int depth = params_.max_depth;
        if (largest < 9 && empties > 7) {
            depth = std::min(depth, 3);
        }
        if (largest >= 11 && empties <= 6) {
            depth = std::max(depth, params_.black_depth);
        }
        if (empties <= 4) {
            depth = std::max(depth, params_.max_depth + 1);
        }
        if (empties <= 3) {
            depth = std::max(depth, params_.max_depth + 2);
        }
        if (empties <= 2) {
            depth = std::max(depth, params_.max_depth + 3);
        }
        int cap = std::min(5, std::max(params_.max_depth + 3, params_.black_depth + 2));
        cap = std::min(cap, std::min(5, params_.max_depth + 2));
        depth = std::min(depth, cap);
        return depth;
    }

    bool timed_out(SearchStats &stats) const {
        if (params_.time_ms <= 0) {
            return false;
        }
        auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now() - started_
        ).count();
        if (elapsed >= params_.time_ms) {
            stats.timed_out = true;
            return true;
        }
        return false;
    }

    double chance_node(Board board, int depth, double probability, SearchStats &stats) {
        ++stats.nodes;
        if (depth <= 0 || probability < params_.probability_cutoff || timed_out(stats)) {
            return eval_board(board);
        }

        auto empty = empty_positions(board);
        if (empty.empty()) {
            return max_node(board, depth - 1, probability, stats);
        }

        int chance_limit = params_.max_chance_cells;
        std::vector<int> cells = selected_chance_cells(board, empty, chance_limit);
        double cell_weight = 1.0 / static_cast<double>(cells.size());
        double total = 0.0;
        for (int index : cells) {
            Board with2 = set_cell(board, index, 1);
            Board with4 = set_cell(board, index, 2);
            double p2 = probability * cell_weight * 0.9;
            double p4 = probability * cell_weight * 0.1;
            total += cell_weight * (
                0.9 * max_node(with2, depth - 1, p2, stats) +
                0.1 * max_node(with4, depth - 1, p4, stats)
            );
            if (timed_out(stats)) {
                break;
            }
        }
        return total;
    }

    double max_node(Board board, int depth, double probability, SearchStats &stats) {
        ++stats.nodes;
        if (depth <= 0 || probability < params_.probability_cutoff || timed_out(stats)) {
            return eval_board(board);
        }

        CacheKey key{board, depth};
        auto found = cache_.find(key);
        if (found != cache_.end()) {
            return found->second;
        }

        double best = kDeadScore;
        auto moves = all_moves(board);
        bool has_safe_milestone_move = false;
        for (const MoveResult &move : moves) {
            if (move.moved && !bad_milestone_merge(board, move.board)) {
                has_safe_milestone_move = true;
                break;
            }
        }
        bool has_endgame_shape_safe_move = false;
        for (const MoveResult &move : moves) {
            if (move.moved && !bad_endgame_shape_move(board, move.board)) {
                has_endgame_shape_safe_move = true;
                break;
            }
        }
        for (int dir = 0; dir < 4; ++dir) {
            const MoveResult &move = moves[dir];
            if (!move.moved) {
                continue;
            }
            if (has_safe_milestone_move && bad_milestone_merge(board, move.board)) {
                continue;
            }
            if (has_endgame_shape_safe_move && bad_endgame_shape_move(board, move.board)) {
                continue;
            }
            int child_depth = depth;
            if (move.reward > 250 && move.reward < 2000 && child_depth > 2) {
                child_depth = std::min(child_depth, move.reward >= 1000 ? 3 : 2);
            }
            double value = processed_reward(move.reward) +
                large_merge_priority_score(board, move.board) +
                milestone_transition_score(board, move.board) +
                chance_node(move.board, child_depth, probability, stats);
            best = std::max(best, value);
        }

        if (best == kDeadScore) {
            best = kDeadScore;
        }
        if (cache_.size() < 2000000) {
            cache_[key] = best;
        }
        return best;
    }

    SearchParams params_;
    std::chrono::steady_clock::time_point started_;
    std::unordered_map<CacheKey, double, CacheKeyHash> cache_;
};

int exponent_from_display_value(int value) {
    if (value == 0) {
        return 0;
    }
    if (value > 0 && (value & (value - 1)) == 0) {
        int exp = 0;
        while ((1 << exp) < value && exp < 15) {
            ++exp;
        }
        return (1 << exp) == value ? exp : -1;
    }
    if (value > 0 && value <= 15) {
        return value;
    }
    return -1;
}

bool parse_display_board(const std::string &text, Board &board) {
    std::vector<int> values;
    int current = 0;
    bool in_number = false;
    bool negative = false;
    auto flush = [&]() {
        if (!in_number) {
            return;
        }
        values.push_back(negative ? -current : current);
        current = 0;
        in_number = false;
        negative = false;
    };

    for (char ch : text) {
        if (ch >= '0' && ch <= '9') {
            current = current * 10 + (ch - '0');
            in_number = true;
        } else {
            flush();
            negative = ch == '-';
        }
    }
    flush();

    if (values.size() != 16) {
        return false;
    }
    Board parsed = 0;
    for (int i = 0; i < 16; ++i) {
        int exp = exponent_from_display_value(values[i]);
        if (exp < 0 || exp > 15) {
            return false;
        }
        parsed = set_cell(parsed, i, exp);
    }
    board = parsed;
    return true;
}

struct Args {
    int depth = 5;
    int black_depth = 5;
    int chance_limit = 6;
    int time_ms = 0;
    std::string choose_board;
};

Args parse_args(int argc, char **argv) {
    Args args;
    for (int i = 1; i < argc; ++i) {
        std::string key = argv[i];
        auto read_int = [&](int &target) {
            if (i + 1 < argc) {
                target = std::atoi(argv[++i]);
            }
        };
        if (key == "--depth") read_int(args.depth);
        else if (key == "--black-depth") read_int(args.black_depth);
        else if (key == "--chance-limit") read_int(args.chance_limit);
        else if (key == "--time-ms") read_int(args.time_ms);
        else if (key == "--choose-board" && i + 1 < argc) args.choose_board = argv[++i];
    }
    return args;
}

}  // namespace

int main(int argc, char **argv) {
    init_tables();
    Args args = parse_args(argc, argv);

    SearchParams params;
    params.max_depth = args.depth;
    params.black_depth = args.black_depth;
    params.max_chance_cells = args.chance_limit;
    params.time_ms = args.time_ms;
    params.probability_cutoff = args.depth >= 6 ? 0.00012 : 0.00006;

    if (!args.choose_board.empty()) {
        Board board = 0;
        if (!parse_display_board(args.choose_board, board)) {
            std::cerr << "invalid_choose_board: expected 16 tile values\n";
            return 1;
        }

        SearchStats stats;
        Expectimax ai(params);
        int dir = ai.choose(board, stats);
        MoveResult move = dir >= 0 ? move_board(board, dir) : MoveResult{};
        std::cout << "{\"dir\":" << dir
                  << ",\"nodes\":" << stats.nodes
                  << ",\"max\":" << max_tile(board)
                  << ",\"moved\":" << (move.moved ? "true" : "false")
                  << ",\"source\":\"search\""
                  << "}\n";
        return 0;
    }

    std::cerr << "missing --choose-board with 16 tile values\n";
    return 1;
}
