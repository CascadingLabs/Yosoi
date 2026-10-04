//! Yosoi-owned classification of bounded main-document response signals.
//!
//! A challenge observation is a durable capture fact. It is never a navigation
//! error and does not request retries, identity changes, or challenge solving.

mod corpus;

use serde::{Deserialize, Serialize};

pub const BROWSER_CHALLENGE_DETECTOR_VERSION: &str = "yosoi.response-challenge.v1";
pub const BROWSER_CHALLENGE_CORPUS_VERSION: &str = "cl-2026.09.24";
pub const BROWSER_CHALLENGE_BODY_PREFIX_LIMIT: usize = 64 * 1024;
const MAX_SUPPORTING_FACTS: usize = 16;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BrowserResponseSignalScope {
    MainDocument,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BrowserResponseSignalUnavailableReason {
    NavigationNotCollected,
    MainDocumentNotObserved,
    StatusNotObserved,
    HeadersOmittedByPolicy,
    BodyOmittedByPolicy,
    BodyRequestFailed,
    BodyUnavailable,
    BodyInvalidEncoding,
    BodyCaptureEnded,
    BodyPrefixTruncated,
    DetectorUnavailable,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum BrowserResponseSignalCompleteness {
    Complete,
    Partial {
        reasons: Vec<BrowserResponseSignalUnavailableReason>,
    },
    Unavailable {
        reason: BrowserResponseSignalUnavailableReason,
    },
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BrowserChallengeState {
    Present,
    Absent,
    Unknown,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BrowserChallengeEvidenceTier {
    None,
    Headers,
    Body,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BrowserChallengeSignalSource {
    Headers,
    Body,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserChallengeSupportingFact {
    vendor: String,
    source: BrowserChallengeSignalSource,
    active_challenge: bool,
}

impl BrowserChallengeSupportingFact {
    pub fn vendor(&self) -> &str {
        &self.vendor
    }

    pub const fn source(&self) -> BrowserChallengeSignalSource {
        self.source
    }

    pub const fn active_challenge(&self) -> bool {
        self.active_challenge
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserChallengeFact {
    scope: BrowserResponseSignalScope,
    completeness: BrowserResponseSignalCompleteness,
    vendors: Vec<String>,
    presence: BrowserChallengeState,
    active_challenge: BrowserChallengeState,
    challenge_vendor: Option<String>,
    evidence: BrowserChallengeEvidenceTier,
    detector_version: String,
    corpus_version: String,
    supporting_facts: Vec<BrowserChallengeSupportingFact>,
}

impl BrowserChallengeFact {
    pub fn unavailable(reason: BrowserResponseSignalUnavailableReason) -> Self {
        Self {
            scope: BrowserResponseSignalScope::MainDocument,
            completeness: BrowserResponseSignalCompleteness::Unavailable { reason },
            vendors: Vec::new(),
            presence: BrowserChallengeState::Unknown,
            active_challenge: BrowserChallengeState::Unknown,
            challenge_vendor: None,
            evidence: BrowserChallengeEvidenceTier::None,
            detector_version: BROWSER_CHALLENGE_DETECTOR_VERSION.to_owned(),
            corpus_version: BROWSER_CHALLENGE_CORPUS_VERSION.to_owned(),
            supporting_facts: Vec::new(),
        }
    }

    pub const fn scope(&self) -> BrowserResponseSignalScope {
        self.scope
    }

    pub const fn completeness(&self) -> &BrowserResponseSignalCompleteness {
        &self.completeness
    }

    pub fn vendors(&self) -> &[String] {
        &self.vendors
    }

    pub const fn presence(&self) -> BrowserChallengeState {
        self.presence
    }

    pub const fn active_challenge(&self) -> BrowserChallengeState {
        self.active_challenge
    }

    pub fn challenge_vendor(&self) -> Option<&str> {
        self.challenge_vendor.as_deref()
    }

    pub const fn evidence(&self) -> BrowserChallengeEvidenceTier {
        self.evidence
    }

    pub fn detector_version(&self) -> &str {
        &self.detector_version
    }

    pub fn corpus_version(&self) -> &str {
        &self.corpus_version
    }

    pub fn supporting_facts(&self) -> &[BrowserChallengeSupportingFact] {
        &self.supporting_facts
    }

    pub(crate) fn is_consistent(&self) -> bool {
        if self.detector_version.trim().is_empty()
            || self.corpus_version.trim().is_empty()
            || self.supporting_facts.len() > MAX_SUPPORTING_FACTS
            || self
                .vendors
                .windows(2)
                .any(|pair| pair.first().zip(pair.last()).is_some_and(|(a, b)| a >= b))
        {
            return false;
        }
        if matches!(
            self.completeness,
            BrowserResponseSignalCompleteness::Unavailable { .. }
        ) {
            return self.vendors.is_empty()
                && self.presence == BrowserChallengeState::Unknown
                && self.active_challenge == BrowserChallengeState::Unknown
                && self.challenge_vendor.is_none()
                && self.evidence == BrowserChallengeEvidenceTier::None
                && self.supporting_facts.is_empty();
        }
        if matches!(
            &self.completeness,
            BrowserResponseSignalCompleteness::Partial { reasons } if reasons.is_empty()
        ) {
            return false;
        }
        if matches!(
            self.completeness,
            BrowserResponseSignalCompleteness::Complete
        ) && (self.presence == BrowserChallengeState::Unknown
            || self.active_challenge == BrowserChallengeState::Unknown)
        {
            return false;
        }
        let presence_matches = match self.presence {
            BrowserChallengeState::Present => !self.vendors.is_empty(),
            BrowserChallengeState::Absent | BrowserChallengeState::Unknown => {
                self.vendors.is_empty()
            }
        };
        let active_matches = match self.active_challenge {
            BrowserChallengeState::Present => {
                self.presence == BrowserChallengeState::Present
                    && self.challenge_vendor.as_ref().is_some_and(|vendor| {
                        self.vendors.contains(vendor)
                            && self
                                .supporting_facts
                                .iter()
                                .any(|fact| fact.active_challenge && &fact.vendor == vendor)
                    })
            }
            BrowserChallengeState::Absent | BrowserChallengeState::Unknown => {
                self.challenge_vendor.is_none()
            }
        };
        let support_matches = self.supporting_facts.iter().all(|fact| {
            self.vendors.contains(&fact.vendor)
                && (!fact.active_challenge
                    || self.active_challenge == BrowserChallengeState::Present)
        });
        let evidence_matches = match self.evidence {
            BrowserChallengeEvidenceTier::None => self.supporting_facts.is_empty(),
            BrowserChallengeEvidenceTier::Headers => {
                !self.supporting_facts.is_empty()
                    && self
                        .supporting_facts
                        .iter()
                        .all(|fact| fact.source == BrowserChallengeSignalSource::Headers)
            }
            BrowserChallengeEvidenceTier::Body => self
                .supporting_facts
                .iter()
                .any(|fact| fact.source == BrowserChallengeSignalSource::Body),
        };
        presence_matches && active_matches && support_matches && evidence_matches
    }
}

#[derive(Clone, Copy, Debug)]
pub enum BrowserResponseBodySignals<'a> {
    Complete(&'a [u8]),
    Truncated { retained: &'a [u8] },
    Omitted,
    Unavailable(BrowserResponseSignalUnavailableReason),
}

#[derive(Clone, Copy, Debug)]
pub struct BrowserResponseSignals<'a> {
    pub scope: BrowserResponseSignalScope,
    pub status: Option<u16>,
    pub headers: Option<&'a [(String, String)]>,
    pub body: BrowserResponseBodySignals<'a>,
}

pub fn classify_browser_challenge(signals: BrowserResponseSignals<'_>) -> BrowserChallengeFact {
    let Some(matches) = corpus::classify(&signals) else {
        return BrowserChallengeFact::unavailable(
            BrowserResponseSignalUnavailableReason::DetectorUnavailable,
        );
    };
    let mut vendors = Vec::new();
    let mut challenge_vendor = None;
    let mut supporting_facts = Vec::new();
    let mut active_supporting_fact = None;
    let mut evidence = BrowserChallengeEvidenceTier::None;
    for matched in matches {
        if !vendors.iter().any(|vendor| vendor == &matched.vendor) {
            vendors.push(matched.vendor.clone());
        }
        if matched.active_challenge && challenge_vendor.is_none() {
            challenge_vendor = Some(matched.vendor.clone());
        }
        if matched.active_challenge && active_supporting_fact.is_none() {
            active_supporting_fact = Some(BrowserChallengeSupportingFact {
                vendor: matched.vendor.clone(),
                source: matched.source,
                active_challenge: true,
            });
        }
        evidence = match (evidence, matched.source) {
            (_, BrowserChallengeSignalSource::Body) => BrowserChallengeEvidenceTier::Body,
            (BrowserChallengeEvidenceTier::None, BrowserChallengeSignalSource::Headers) => {
                BrowserChallengeEvidenceTier::Headers
            }
            (current, BrowserChallengeSignalSource::Headers) => current,
        };
        let duplicate = supporting_facts
            .iter()
            .any(|fact: &BrowserChallengeSupportingFact| {
                fact.vendor == matched.vendor
                    && fact.source == matched.source
                    && fact.active_challenge == matched.active_challenge
            });
        if !duplicate && supporting_facts.len() < MAX_SUPPORTING_FACTS {
            supporting_facts.push(BrowserChallengeSupportingFact {
                vendor: matched.vendor,
                source: matched.source,
                active_challenge: matched.active_challenge,
            });
        }
    }
    if let Some(active) = active_supporting_fact
        && !supporting_facts.iter().any(|fact| fact.active_challenge)
    {
        if supporting_facts.len() >= MAX_SUPPORTING_FACTS {
            supporting_facts.pop();
        }
        supporting_facts.push(active);
    }
    vendors.sort();
    let (completeness, enough_to_prove_absence) = completeness(&signals);
    let presence = if vendors.is_empty() {
        if enough_to_prove_absence {
            BrowserChallengeState::Absent
        } else {
            BrowserChallengeState::Unknown
        }
    } else {
        BrowserChallengeState::Present
    };
    let active_challenge = if challenge_vendor.is_some() {
        BrowserChallengeState::Present
    } else if enough_to_prove_absence {
        BrowserChallengeState::Absent
    } else {
        BrowserChallengeState::Unknown
    };
    BrowserChallengeFact {
        scope: signals.scope,
        completeness,
        vendors,
        presence,
        active_challenge,
        challenge_vendor,
        evidence,
        detector_version: BROWSER_CHALLENGE_DETECTOR_VERSION.to_owned(),
        corpus_version: BROWSER_CHALLENGE_CORPUS_VERSION.to_owned(),
        supporting_facts,
    }
}

fn completeness(signals: &BrowserResponseSignals<'_>) -> (BrowserResponseSignalCompleteness, bool) {
    let mut reasons = Vec::new();
    if signals.status.is_none() {
        reasons.push(BrowserResponseSignalUnavailableReason::StatusNotObserved);
    }
    let headers_complete = signals.headers.is_some();
    if !headers_complete {
        reasons.push(BrowserResponseSignalUnavailableReason::HeadersOmittedByPolicy);
    }
    let body_complete = match signals.body {
        BrowserResponseBodySignals::Complete(_) => true,
        BrowserResponseBodySignals::Truncated { retained }
            if retained.len() >= BROWSER_CHALLENGE_BODY_PREFIX_LIMIT =>
        {
            true
        }
        BrowserResponseBodySignals::Truncated { .. } => {
            reasons.push(BrowserResponseSignalUnavailableReason::BodyPrefixTruncated);
            false
        }
        BrowserResponseBodySignals::Omitted => {
            reasons.push(BrowserResponseSignalUnavailableReason::BodyOmittedByPolicy);
            false
        }
        BrowserResponseBodySignals::Unavailable(reason) => {
            reasons.push(reason);
            false
        }
    };
    let enough_to_prove_absence = headers_complete && body_complete;
    if reasons.is_empty() {
        (
            BrowserResponseSignalCompleteness::Complete,
            enough_to_prove_absence,
        )
    } else {
        (
            BrowserResponseSignalCompleteness::Partial { reasons },
            enough_to_prove_absence,
        )
    }
}
