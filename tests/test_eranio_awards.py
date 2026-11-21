import inspect

from TwitchChannelPointsMiner.classes import Twitch as twitch_module
from TwitchChannelPointsMiner.classes.entities.Campaign import Campaign
from TwitchChannelPointsMiner.eranio import awards

PREFIX = "3346bf0d-5179-4a89-b760-13e1581dfd12_CUSTOM_ID_"


def drop(drop_id, name, minutes, benefit_id, benefit_name, start, end):
    return {
        "id": drop_id,
        "name": name,
        "requiredMinutesWatched": minutes,
        "startAt": start,
        "endAt": end,
        "benefitEdges": [{"benefit": {"id": benefit_id, "name": benefit_name}}],
        "self": None,
    }


def campaign(campaign_id, name, drops, start, end):
    return {
        "id": campaign_id,
        "name": name,
        "status": "ACTIVE",
        "game": {"displayName": "Black Desert"},
        "startAt": start,
        "endAt": end,
        "timeBasedDrops": drops,
    }


START = "2020-11-20T12:00:00Z"
END = "2099-11-21T11:59:59.999Z"


def master_class():
    return campaign(
        "e1b1",
        "Master Class 26 (Nov 20)",
        [
            drop(
                "d1",
                "1 Hour (Nov 20)",
                60,
                PREFIX + "MASTERCLASS2601A",
                "1 Hour Reward",
                START,
                END,
            ),
            drop(
                "d2",
                "2 Hour (Nov 20)",
                120,
                PREFIX + "MASTERCLASS2601B",
                "2 Hour Reward",
                START,
                END,
            ),
        ],
        START,
        END,
    )


def older_campaign():
    return campaign(
        "c981",
        "2026 BDO Drops (Nov 19)",
        [
            drop(
                "d9",
                "2 Hour (Nov 19)",
                120,
                PREFIX + "TWITCHDROP261101",
                "2 Hour Reward",
                START,
                END,
            )
        ],
        START,
        END,
    )


def inventory(awards_list, in_progress=None):
    return {
        "dropCampaignsInProgress": in_progress or [],
        "gameEventDrops": [
            {"id": award_id, "name": "x", "lastAwardedAt": at}
            for award_id, at in awards_list
        ],
    }


AWARDED = [
    (PREFIX + "MASTERCLASS2601A", "2026-11-20T18:06:06.531Z"),
    (PREFIX + "MASTERCLASS2601B", "2026-11-21T00:53:50.143Z"),
]


def test_awarded_drops_count_even_when_the_reward_name_repeats_elsewhere():
    details = [master_class(), older_campaign()]
    shared = awards.shared_benefit_ids(details)
    entity = Campaign(details[0])
    marked = awards.mark_awarded(entity, inventory(AWARDED), shared)
    assert [d.name for d in marked] == ["1 Hour (Nov 20)", "2 Hour (Nov 20)"]
    entity.clear_drops()
    assert entity.drops == []


def test_a_campaign_still_in_progress_is_left_to_the_inventory():
    entity = Campaign(master_class())
    progress = [{"id": "e1b1", "timeBasedDrops": []}]
    assert awards.mark_awarded(entity, inventory(AWARDED, progress), set()) == []
    assert all(d.is_claimed is False for d in entity.drops)


def test_an_award_outside_the_drop_window_does_not_count():
    entity = Campaign(master_class())
    old = [(PREFIX + "MASTERCLASS2601A", "2019-01-01T00:00:00Z")]
    assert awards.mark_awarded(entity, inventory(old), set()) == []


def test_a_benefit_shared_by_several_drops_is_not_trusted():
    details = [master_class(), master_class()]
    details[1]["id"] = "other"
    shared = awards.shared_benefit_ids(details)
    entity = Campaign(details[0])
    assert awards.mark_awarded(entity, inventory(AWARDED), shared) == []


def test_missing_inventory_changes_nothing():
    entity = Campaign(master_class())
    assert awards.mark_awarded(entity, None, set()) == []
    assert awards.mark_awarded(entity, {"gameEventDrops": []}, set()) == []


def test_the_report_is_logged_once(caplog):
    caplog.set_level("INFO")
    awards.REPORTED.clear()
    for _ in range(2):
        awards.mark_awarded(Campaign(master_class()), inventory(AWARDED), set())
    assert (
        caplog.text.count("2 Hour (Nov 20) wurde von Twitch schon gutgeschrieben") == 1
    )


def test_campaign_sync_uses_the_award_check():
    text = inspect.getsource(twitch_module.Twitch.sync_campaigns)
    assert "eranio_awards.mark_awarded(" in text
    assert text.index("eranio_awards.mark_awarded(") < text.index(
        "eranio_drops.remember(campaign)"
    )
