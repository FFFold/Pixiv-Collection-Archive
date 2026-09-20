from pixiv_archive.sync.rank import RANK_SPACING, full_rank, incremental_ranks


def test_incremental_ranks_empty():
    assert incremental_ranks(None, 0) == []
    assert incremental_ranks(500, 0) == []


def test_incremental_ranks_first_batch_places_newest_first():
    ranks = incremental_ranks(None, 3)
    assert ranks == [-3072, -2048, -1024]
    # index 0 is the newest bookmark -> smallest rank -> appears first
    assert ranks == sorted(ranks)
    assert len(set(ranks)) == 3


def test_incremental_ranks_second_batch_is_placed_in_front():
    first = incremental_ranks(None, 2)
    second = incremental_ranks(min(first), 2)
    assert all(r < min(first) for r in second)
    assert second == sorted(second)


def test_incremental_ranks_preserve_listing_order_within_batch():
    ranks = incremental_ranks(0, 4)
    assert ranks[0] < ranks[1] < ranks[2] < ranks[3]


def test_incremental_ranks_spacing_is_constant():
    ranks = incremental_ranks(None, 5)
    gaps = {b - a for a, b in zip(ranks, ranks[1:], strict=False)}
    assert gaps == {RANK_SPACING}


def test_full_rank_is_position_times_spacing():
    assert full_rank(0) == 0
    assert full_rank(1) == RANK_SPACING
    assert full_rank(100) == 100 * RANK_SPACING
