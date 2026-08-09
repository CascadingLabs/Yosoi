"""SQLite persistence for proven action episodes and exact replay projections."""

from __future__ import annotations

from yosoi.a3.models import ActionEpisode, ActionReplayPlan
from yosoi.storage.sqlite_store import YosoiSQLiteStore

_EPISODES = 'a3_action_episodes'
_PLANS = 'a3_action_plans'


class ActionEpisodeStore(YosoiSQLiteStore):
    """Persist immutable source episodes and their conservative replay plans."""

    async def save_episode(self, episode: ActionEpisode) -> None:
        """Upsert one full-fidelity episode under its canonical fingerprint."""
        await self._ensure_migrated()
        client = await self._connect()
        await client.execute(
            f"""
            INSERT INTO {_EPISODES} (fingerprint, episode_id, schema_version, payload)
            VALUES (:fingerprint, :episode_id, :schema_version, json(:payload))
            ON CONFLICT(fingerprint) DO UPDATE SET payload = excluded.payload
            """,
            {
                'fingerprint': episode.fingerprint,
                'episode_id': episode.episode_id,
                'schema_version': episode.schema_version,
                'payload': episode.model_dump_json(),
            },
        )

    async def load_episode(self, fingerprint: str) -> ActionEpisode | None:
        """Load one exact episode, or ``None`` when unknown."""
        await self._ensure_migrated()
        client = await self._connect()
        result = await client.execute(
            f'SELECT json(payload) AS payload FROM {_EPISODES} WHERE fingerprint = :fingerprint',
            {'fingerprint': fingerprint},
        )
        if not result.rows:
            return None
        return ActionEpisode.model_validate_json(str(result.rows[0][0]))

    async def save_plan(self, plan: ActionReplayPlan) -> None:
        """Upsert one exact replay projection under its deterministic plan id."""
        await self._ensure_migrated()
        if await self.load_episode(plan.source_episode_fingerprint) is None:
            raise ValueError('cannot store a replay plan without its source episode')
        client = await self._connect()
        await client.execute(
            f"""
            INSERT INTO {_PLANS} (plan_id, source_episode_fingerprint, schema_version, payload)
            VALUES (:plan_id, :source_episode_fingerprint, :schema_version, json(:payload))
            ON CONFLICT(plan_id) DO UPDATE SET payload = excluded.payload
            """,
            {
                'plan_id': plan.plan_id,
                'source_episode_fingerprint': plan.source_episode_fingerprint,
                'schema_version': plan.schema_version,
                'payload': plan.model_dump_json(),
            },
        )

    async def load_plan(self, plan_id: str) -> ActionReplayPlan | None:
        """Load one exact replay plan, or ``None`` when unknown."""
        await self._ensure_migrated()
        client = await self._connect()
        result = await client.execute(
            f'SELECT json(payload) AS payload FROM {_PLANS} WHERE plan_id = :plan_id',
            {'plan_id': plan_id},
        )
        if not result.rows:
            return None
        return ActionReplayPlan.model_validate_json(str(result.rows[0][0]))

    async def _ensure_migrated(self) -> None:
        if self._migrated:
            return
        client = await self._connect()
        await client.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_EPISODES} (
                fingerprint TEXT PRIMARY KEY,
                episode_id TEXT NOT NULL,
                schema_version TEXT NOT NULL,
                payload JSON NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await client.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_PLANS} (
                plan_id TEXT PRIMARY KEY,
                source_episode_fingerprint TEXT NOT NULL,
                schema_version TEXT NOT NULL,
                payload JSON NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(source_episode_fingerprint) REFERENCES {_EPISODES}(fingerprint)
            )
            """
        )
        self._migrated = True


__all__ = ['ActionEpisodeStore']
