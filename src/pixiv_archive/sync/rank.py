"""Rank allocation for bookmark ordering.

Rank is an integer where smaller means "more recently bookmarked", so that
ordering by rank ascending reproduces the pixiv bookmark list order.

Bookmarks are given sparse ranks (multiples of ``RANK_SPACING``) so that new
batches can always be inserted in front with O(1) work and without touching
existing rows.
"""

RANK_SPACING = 1024


def incremental_ranks(min_rank: int | None, count: int) -> list[int]:
    """Ranks for a batch of newly discovered bookmarks, newest first.

    The whole batch is placed in front of every existing bookmark while
    preserving the listing order: index 0 receives the smallest rank.
    """
    if count <= 0:
        return []
    base = (min_rank if min_rank is not None else 0) - RANK_SPACING * count
    return [base + RANK_SPACING * i for i in range(count)]


def full_rank(position: int) -> int:
    """Rank for a bookmark at a known global list position (0 = newest)."""
    return position * RANK_SPACING
