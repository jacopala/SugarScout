"""Voice turns, wake phrase, mood check-ins. Speech and model are faked (no network)."""

from __future__ import annotations

import base64
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sugarscout.ai.speech import clean_for_speech, pcm_to_wav
from sugarscout.ai.summary import compute_stats
from sugarscout.ai.wake import parse_wake
from sugarscout.api.main import create_app
from sugarscout.demo import DEMO_CHILD_ID, ensure_demo_child
from sugarscout.mood import MOOD_REPLIES
from sugarscout.settings import Settings
from tests.test_chat import FakeModel

CLIP = pcm_to_wav(b"\x00\x00" * 8000, 16_000)  # 0.5 s of silence, 16 kHz mono


class FakeSpeech:
    def __init__(
        self, transcript: str = "", fail_asr: bool = False, fail_tts: bool = False
    ) -> None:
        self.transcript = transcript
        self.fail_asr = fail_asr
        self.fail_tts = fail_tts
        self.spoken: list[str] = []

    async def transcribe(self, pcm16k: bytes) -> str:
        if self.fail_asr:
            raise TimeoutError("asr down")
        return self.transcript

    async def synthesize(self, text: str) -> bytes:
        if self.fail_tts:
            raise TimeoutError("tts down")
        self.spoken.append(text)
        return pcm_to_wav(b"\x01\x00" * 100, 22_050)


@pytest.mark.parametrize(
    ("transcript", "woke", "command"),
    [
        ("Hey Scout, tell me a joke.", True, "tell me a joke"),
        ("hey scott tell me a joke", True, "tell me a joke"),
        ("Okay scout. I feel shaky", True, "I feel shaky"),
        ("Hey Scout.", True, ""),
        ("Hay Scout.", True, ""),  # what Parakeet actually returned for "Hey Scout."
        ("Scout!", True, ""),
        ("I'm scouting for cookies", False, ""),
        ("the boy scout was here", False, ""),
        ("tell me a joke", False, ""),
    ],
)
def test_parse_wake(transcript: str, woke: bool, command: str) -> None:
    assert parse_wake(transcript) == (woke, command)


def test_clean_for_speech_drops_emoji_and_markdown() -> None:
    assert clean_for_speech("Yay! 🍪😂 **Great** job") == "Yay! Great job"


@pytest.fixture
async def api(
    settings: Settings, engine: AsyncEngine, redis: Redis
) -> AsyncIterator[tuple[AsyncClient, object]]:
    await redis.flushdb()
    await ensure_demo_child(engine, settings)
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        app.state.llm = FakeModel(reply="Why did the cookie go to the doctor? It felt crummy! 🍪")
        yield c, app
    async with engine.begin() as conn:
        for table in ("chat_messages", "mood_checkins", "alerts"):
            await conn.execute(
                text(f"DELETE FROM {table} WHERE child_id = :c"), {"c": DEMO_CHILD_ID}
            )


async def _turn(c: AsyncClient, awake: bool = False) -> dict[str, object]:
    r = await c.post(
        f"/voice/turn?awake={'true' if awake else 'false'}",
        content=CLIP,
        headers={"Content-Type": "audio/wav"},
    )
    assert r.status_code == 200, r.text
    data: dict[str, object] = r.json()
    return data


async def test_speech_without_wake_word_is_ignored_and_not_stored(
    api: tuple[AsyncClient, object], engine: AsyncEngine
) -> None:
    c, app = api
    app.state.speech = FakeSpeech("so then my brother said")  # type: ignore[attr-defined]
    data = await _turn(c)
    assert data["heard"] is False
    assert data["transcript"] is None, "overheard speech is never returned"
    async with engine.connect() as conn:
        n = (
            await conn.execute(
                text("SELECT count(*) FROM chat_messages WHERE child_id = :c"), {"c": DEMO_CHILD_ID}
            )
        ).scalar_one()
    assert n == 0, "overheard speech is never stored"


async def test_wake_word_with_request_replies_with_audio(api: tuple[AsyncClient, object]) -> None:
    c, app = api
    speech = FakeSpeech("Hey Scout, tell me a joke")
    app.state.speech = speech  # type: ignore[attr-defined]
    data = await _turn(c)
    assert data["heard"] and data["woke"]
    assert data["transcript"] == "tell me a joke"
    assert "crummy" in str(data["reply"])
    assert base64.b64decode(str(data["audio"]))[:4] == b"RIFF"
    assert speech.spoken == ["Why did the cookie go to the doctor? It felt crummy!"], (
        "emoji not spoken"
    )


async def test_wake_word_alone_acknowledges_and_stays_awake(
    api: tuple[AsyncClient, object],
) -> None:
    c, app = api
    app.state.speech = FakeSpeech("Hey Scout")  # type: ignore[attr-defined]
    data = await _turn(c)
    assert data["woke"] and data["awake_for_s"] == 8
    assert data["reply"] == "I'm listening!"
    app.state.speech = FakeSpeech("what's your favorite color")  # type: ignore[attr-defined]
    follow_up = await _turn(c, awake=True)
    assert follow_up["heard"] and follow_up["transcript"] == "what's your favorite color"


async def test_spoken_emergency_still_bypasses_model_and_escalates(
    api: tuple[AsyncClient, object], engine: AsyncEngine
) -> None:
    c, app = api
    app.state.speech = FakeSpeech("Hey Scout I feel really dizzy and shaky")  # type: ignore[attr-defined]
    model = FakeModel()
    app.state.llm = model  # type: ignore[attr-defined]
    data = await _turn(c)
    assert data["escalated"] is True and data["flagged"] == "emergency"
    assert model.calls == []
    async with engine.connect() as conn:
        rule = (
            await conn.execute(
                text("SELECT rule_type FROM alerts WHERE child_id = :c AND state = 'open'"),
                {"c": DEMO_CHILD_ID},
            )
        ).scalar_one()
    assert rule == "emergency_language"


async def test_tts_failure_still_returns_text(api: tuple[AsyncClient, object]) -> None:
    c, app = api
    app.state.speech = FakeSpeech("hey scout hi", fail_tts=True)  # type: ignore[attr-defined]
    data = await _turn(c)
    assert data["reply"] and data["audio"] is None, "browser voice takes over"


async def test_asr_failure_and_bad_audio_are_clean_errors(api: tuple[AsyncClient, object]) -> None:
    c, app = api
    app.state.speech = FakeSpeech(fail_asr=True)  # type: ignore[attr-defined]
    r = await c.post("/voice/turn", content=CLIP)
    assert r.status_code == 502
    r = await c.post("/voice/turn", content=b"not a wav file")
    assert r.status_code == 400
    app.state.speech = None  # type: ignore[attr-defined]
    r = await c.post("/voice/turn", content=CLIP)
    assert r.status_code == 503


async def test_mood_checkin_saves_time_replies_and_reaches_scout(
    api: tuple[AsyncClient, object], engine: AsyncEngine
) -> None:
    c, app = api
    assert (await c.post("/checkins", json={"mood": 0})).status_code == 422
    assert (await c.post("/checkins", json={"mood": 6})).status_code == 422

    r = await c.post("/checkins", json={"mood": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["label"] == "not great" and body["reply"] == MOOD_REPLIES[2]
    assert body["created_at"]

    listed = (await c.get("/checkins")).json()
    assert [x["mood"] for x in listed][:1] == [2]

    model = FakeModel()
    app.state.llm = model  # type: ignore[attr-defined]
    await c.post("/chat", json={"message": "hi"})
    assert "2 out of 5 (not great), just now" in model.calls[-1][0]["content"]

    stats = await compute_stats(engine, DEMO_CHILD_ID)
    assert stats["mood_checkins"] >= 1 and stats["latest_mood"] == 2
    assert stats["low_mood_checkins"] >= 1
