"""Publishing preparation. NOTHING here posts to Instagram.

Automatic publishing needs a Business/Creator account, a Facebook Page link and a
Meta developer app with approved permissions; that is NOT implemented. Today the
supported path is: approve in the dashboard, download the MP4, copy the caption,
post from your phone.
"""
from __future__ import annotations


class NotApproved(Exception):
    pass


def assert_publishable(project: dict) -> None:
    """Every future publisher must call this first."""
    if project.get("status") != "approved" or (project.get("approval") or {}).get("decision") != "approved":
        raise NotApproved("Project has not been approved by a human.")
    if (project.get("qa") or {}).get("status") == "fail":
        raise NotApproved("Quality checks failed.")


def instagram_package(project: dict) -> dict:
    pub = project.get("publish") or {}
    assets = project.get("assets") or {}
    return {"video_url": assets.get("video_url"), "thumbnail_url": assets.get("thumbnail_url"),
            "caption": pub.get("caption", ""), "hashtags": pub.get("hashtags", []),
            "suggested_time": pub.get("suggested_time", ""),
            "checklist": ["Watch the full video with sound", "Verify every item under 'claims to verify'",
                          "Confirm the music and voice licences shown in the report",
                          "Keep the stock-media credit line in the caption"]}


class InstagramPublisher:
    """Interface only. Implement against the official Instagram Graph API when eligible."""

    def publish(self, project: dict) -> None:
        assert_publishable(project)
        raise NotImplementedError("Instagram publishing is not implemented (pending Meta app setup).")
