"""Durable replay contracts for MCP-discovered browser lessons."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from yosoi.models.selectors import SelectorEntry
from yosoi.models.snapshot import SelectorSnapshot


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class ReplayStatus(str, Enum):
    """Operational state for a persisted discovery lesson."""

    ACTIVE = 'active'
    STALE = 'stale'
    DISABLED = 'disabled'


class ActKind(str, Enum):
    """Browser action kinds that can be replayed deterministically."""

    NAVIGATE = 'navigate'
    CLICK = 'click'
    TYPE = 'type'
    SCROLL = 'scroll'
    WAIT = 'wait'
    EVAL = 'eval'
    TELEPORT = 'teleport'
    DOWNLOAD = 'download'  # ys.File() download node (see runtime._download)
    # --- Recovery primitives (W1) ----------------------------------------------------
    # The closed set a REACTION's recovery subtree composes / the discovery layer
    # patches with. They live on the deterministic hot path (CAS-87): each maps to a
    # _RECOVERY_LEAVES executor built ONLY from primitives already on PooledTab
    # (eval_js / dispatch_mouse_event). No solver/LLM call ever lands here — the actual
    # solve happens OFF the hot path in PLANE B and is injected as a pre-resolved leaf.
    CAPTCHA_PROBE = 'captcha_probe'  # eval_js(CAPTURE_JS) -> CaptchaInfo dict | None
    INJECT_TOKEN = 'inject_token'  # eval_js(INJECT_JS, kind, token) — pre-resolved token
    HUMAN_CLICK = 'human_click'  # replay a recorded dispatch_mouse_event recipe


class AssertKind(str, Enum):
    """Observable condition kinds used by replay-node assess/expect steps."""

    URL = 'url'
    SELECTOR = 'selector'
    TEXT = 'text'
    COUNT = 'count'
    DOM_STABLE = 'dom_stable'
    AX_TARGET = 'ax_target'
    ABSENT = 'absent'
    ABSENT_AX_TARGET = 'absent_ax_target'
    DOWNLOAD_OK = 'download_ok'  # a verified download was captured for the node's act
    CAPTCHA = 'captcha'  # trigger guard (W1): a rendered antibot/captcha wall is present
    NONE = 'none'


class ReplayCondition(BaseModel):
    """An observable page condition for assess/assert phases."""

    kind: AssertKind = AssertKind.NONE
    selector: SelectorEntry | None = None
    value: str | int | float | bool | None = None
    timeout_ms: int = Field(default=5000, ge=0)
    quiet_ms: int | None = Field(default=None, ge=0)


class ReplayAct(BaseModel):
    """A deterministic browser action with an ordered target cascade."""

    kind: ActKind
    url: str | None = None
    text: str | None = None
    script: str | None = None
    targets: list[SelectorEntry] = Field(default_factory=list)
    repeat: bool = False
    max_repeats: int = Field(default=1, ge=1)
    dwell_ms: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    output_field: str | None = None

    @model_validator(mode='after')
    def validate_action_payload(self) -> ReplayAct:
        """Require the payload shape needed by action kinds that cannot infer it."""
        if self.kind == ActKind.NAVIGATE and not self.url:
            raise ValueError('navigate acts require url')
        if self.kind == ActKind.CLICK and not self.targets:
            raise ValueError('click acts require at least one target')
        if self.kind == ActKind.TYPE and (not self.targets or self.text is None):
            raise ValueError('type acts require targets and text')
        if self.kind == ActKind.EVAL and not self.script:
            raise ValueError('eval acts require script')
        if self.kind == ActKind.DOWNLOAD:
            if not (self.targets or self.url):
                raise ValueError('download acts require targets (retrigger) or url (refetch)')
            if self.repeat:
                raise ValueError('download acts cannot repeat')
        return self


class ReplayNode(BaseModel):
    """Assess / Act / Assert replay primitive."""

    id: str
    intent: str
    assess: ReplayCondition = Field(default_factory=ReplayCondition)
    act: ReplayAct
    expect: ReplayCondition = Field(default_factory=ReplayCondition)


class TeleportSpec(BaseModel):
    """Geolocation/locale spoof applied BEFORE a plan's first navigate.

    This is the teleport-before-first-paint contract. A free-floating
    ``ActKind.TELEPORT`` node leaves the spoof's ordering relative to the first
    ``NAVIGATE`` up to whatever index discovery happened to emit it at; CDP's
    ``Emulation.setGeolocationOverride`` is a *session-level* override that must
    be installed before the page loads to be reflected on first paint. Lifting
    the spoof to a per-plan field that ``execute_plan`` applies *before* the node
    loop makes "after a navigate" structurally impossible — no node-order
    scanning validator needed.

    The coordinates are LITERAL: discovery geocodes ``city, state`` → ``(lat,
    lon)`` and bakes the result here, so replay never imports geopy and stays
    import-light (CAS-87). A ``words``-localization plan carries NO ``TeleportSpec``
    (city/state is baked into the query string instead); only a ``teleport``
    plan sets one.
    """

    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    timezone: str | None = None
    locale: str | None = None


class NodeKind(str, Enum):
    """Composite/leaf kinds for the behavior-tree replay model (W1).

    The tree is ADDITIVE over the legacy flat ``ReplayPlan.nodes`` list:
    :meth:`ReplayPlan.compile` wraps a flat plan in a single ``SEQUENCE`` of
    ``LEAF`` nodes, so there is exactly one execution code path
    (:func:`yosoi.core.replay.runtime.execute_tree`) and zero breakage for
    existing flat plans.
    """

    LEAF = 'leaf'  # wraps exactly one ReplayNode (today's assess/act/expect)
    SEQUENCE = 'sequence'  # tick children L->R; fail-fast on first child failure
    SELECTOR = 'selector'  # tick children L->R; succeed on first child success
    REACTION = 'reaction'  # decorator: guard one child subtree with trigger->recovery


class ReactionState(str, Enum):
    """Whether a REACTION already knows how to recover, or must learn it.

    * ``LEARNED`` — ``recovery`` is a pinned subtree of :data:`ActKind` recovery
      leaves; ticking it is deterministic and stays on the hot path (CAS-87).
    * ``UNLEARNED`` — only a ``description`` placeholder is known. On a fired
      trigger the walker resolves the description OFF the hot path (PLANE B, via
      the DiscoveryBus) into a recovery leaf, hot-swaps it in, and persists it.
      A captcha intent and a drifted data selector are the same event here.
    """

    LEARNED = 'learned'
    UNLEARNED = 'unlearned'


class TreeNode(BaseModel):
    """A node in a replay behavior tree (W1).

    Exactly one of the kind-specific payloads is meaningful per ``kind``:

    * ``LEAF``     → ``leaf`` (a :class:`ReplayNode`).
    * ``SEQUENCE`` / ``SELECTOR`` → ``children``.
    * ``REACTION`` → ``child`` (the guarded subtree) plus ``trigger`` and either
      a ``recovery`` subtree (``state == LEARNED``) or a ``description``
      (``state == UNLEARNED``) that PLANE B resolves into one.
    """

    kind: NodeKind
    id: str
    # LEAF:
    leaf: ReplayNode | None = None
    # SEQUENCE / SELECTOR:
    children: list[TreeNode] = Field(default_factory=list)
    # REACTION (decorator over exactly one child):
    child: TreeNode | None = None
    trigger: ReplayCondition | None = None
    recovery: TreeNode | None = None
    resume: bool = True  # re-tick the guarded child after recovery succeeds
    state: ReactionState = ReactionState.LEARNED
    description: str | None = None  # UNLEARNED: the intent the bus resolves->recovery leaf

    @model_validator(mode='after')
    def _validate_kind_payload(self) -> TreeNode:
        """Reject structurally-impossible trees up front (fail-fast authoring)."""
        if self.kind is NodeKind.LEAF and self.leaf is None:
            raise ValueError('LEAF nodes require a leaf ReplayNode')
        if self.kind is NodeKind.REACTION:
            if self.child is None:
                raise ValueError('REACTION nodes decorate exactly one child')
            if self.trigger is None:
                raise ValueError('REACTION nodes require a trigger condition')
            if self.state is ReactionState.LEARNED and self.recovery is None:
                raise ValueError('LEARNED REACTION nodes require a recovery subtree')
            if self.state is ReactionState.UNLEARNED and not self.description:
                raise ValueError('UNLEARNED REACTION nodes require a description to resolve')
        return self


class ReplayPlan(BaseModel):
    """A learned browser program — flat node list and/or a behavior tree.

    ``nodes`` is the legacy flat sequence and stays the authoring surface for
    existing discovery code. ``tree`` is the additive behavior-tree form (W1).
    :meth:`compile` returns a single ``TreeNode`` for either shape, so the
    runtime has one execution path.
    """

    nodes: list[ReplayNode] = Field(default_factory=list)
    tree: TreeNode | None = None
    teleport: TeleportSpec | None = None
    version: int = 2

    @property
    def is_empty(self) -> bool:
        """Return whether the plan has no browser actions."""
        return self.tree is None and len(self.nodes) == 0

    def compile(self) -> TreeNode:
        """Return the behavior tree for this plan — the single execution form.

        If ``tree`` is set it is returned verbatim. Otherwise the flat ``nodes``
        list is wrapped in one ``SEQUENCE`` of ``LEAF`` nodes, preserving the
        exact left-to-right fail-fast semantics ``execute_plan`` had. This is the
        zero-breakage bridge: a legacy flat plan and a hand-built tree both
        reduce to one ``TreeNode`` the walker ticks.
        """
        if self.tree is not None:
            return self.tree
        return TreeNode(
            kind=NodeKind.SEQUENCE,
            id='__plan_root__',
            children=[TreeNode(kind=NodeKind.LEAF, id=node.id, leaf=node) for node in self.nodes],
        )


class VerifyReport(BaseModel):
    """Replay verification result used as a lesson staleness oracle."""

    passed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    failures: list[str] = Field(default_factory=list)

    @property
    def total(self) -> int:
        """Total number of assertions considered."""
        return self.passed + self.failed

    @property
    def score(self) -> float:
        """Pass ratio, with an empty report considered fully passing."""
        if self.total == 0:
            return 1.0
        return self.passed / self.total


class LessonKey(BaseModel):
    """Stable identity for a discovery lesson.

    Two cache shapes coexist:

    * **per-destination** (default) — keyed by ``domain`` (the target page's
      host). This is the discover-once-per-target unit the static/MCP pipelines
      use today.
    * **per-engine** (hotpath) — when ``engine_host`` is set, identity is the
      ENGINE/TOOL host (``google.com``, ``similarweb.com``) plus ``param_keys``
      (e.g. ``('d',)`` for ``{d}``, ``('q',)`` for a SERP query). The target
      domain is no longer part of identity; it becomes a replay-time param. This
      is the inversion the Nimbal hotpath needs — one program per engine replayed
      across N targets — and ``storage_key`` keeps the two namespaces disjoint.
    """

    domain: str
    contract_signature: str
    page_profile: str = 'default'
    mode: Literal['mcp'] = 'mcp'
    engine_host: str | None = None
    param_keys: tuple[str, ...] = ()
    sig_version: str = Field(
        default='',
        description=(
            'Signature-scheme version that produced contract_signature. Lets a '
            'load-miss after a scheme bump be reported STALE instead of a silent '
            "re-discovery. Empty means a pre-versioning ('v1') lesson; "
            'derived from contract_signature when unset.'
        ),
    )

    @model_validator(mode='after')
    def _default_sig_version(self) -> LessonKey:
        """Derive sig_version from contract_signature's prefix when unset."""
        if not self.sig_version:
            from yosoi.utils.signatures import signature_scheme_of

            object.__setattr__(self, 'sig_version', signature_scheme_of(self.contract_signature))
        return self

    @property
    def storage_key(self) -> str:
        """Filesystem-safe key for lesson persistence.

        Per-destination keys (no ``engine_host``) are byte-identical to the
        legacy format so existing lessons keep loading. Per-engine keys add an
        ``engine``/``params`` segment so they cannot collide with a domain-keyed
        lesson for the same contract.
        """
        if self.engine_host is not None:
            params = '-'.join(self.param_keys)
            raw = f'engine_{self.engine_host}__{self.contract_signature}__{params}__{self.page_profile}__{self.mode}'
        else:
            raw = f'{self.domain}__{self.contract_signature}__{self.page_profile}__{self.mode}'
        return ''.join(ch if ch.isalnum() or ch in ('-', '_') else '_' for ch in raw)


class LessonTrace(BaseModel):
    """Trace references for auditing how a lesson was learned."""

    langfuse_trace_id: str | None = None
    opencode_session_id: str | None = None
    transcript_digest: str | None = None


class LessonProvenance(BaseModel):
    """Version and model metadata for a learned lesson."""

    discovered_at: AwareDatetime = Field(default_factory=utc_now)
    model_name: str | None = None
    provider: str | None = None
    yosoi_version: str | None = None
    voidcrawl_version: str | None = None


class LessonStats(BaseModel):
    """Replay counters and failure audit state."""

    replay_count: int = Field(default=0, ge=0)
    failure_count: int = Field(default=0, ge=0)
    last_replayed_at: AwareDatetime | None = None
    last_verified_at: AwareDatetime | None = None
    last_failed_at: AwareDatetime | None = None


class LessonValidation(BaseModel):
    """Validation evidence captured before a lesson becomes active."""

    report: VerifyReport = Field(default_factory=VerifyReport)
    threshold: float = Field(default=1.0, ge=0.0, le=1.0)
    sample_values: dict[str, Any] = Field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """Return whether the report meets the configured threshold."""
        return self.report.score >= self.threshold


class DiscoveryLesson(BaseModel):
    """Persisted MCP discovery artifact for replay-first scraping."""

    key: LessonKey
    replay_plan: ReplayPlan
    selectors: dict[str, SelectorSnapshot]
    validation: LessonValidation = Field(default_factory=LessonValidation)
    trace: LessonTrace = Field(default_factory=LessonTrace)
    provenance: LessonProvenance = Field(default_factory=LessonProvenance)
    stats: LessonStats = Field(default_factory=LessonStats)
    status: ReplayStatus = ReplayStatus.ACTIVE
    status_reason: str | None = None

    @property
    def is_active(self) -> bool:
        """Return whether the lesson is eligible for replay."""
        return self.status == ReplayStatus.ACTIVE and self.validation.passed
