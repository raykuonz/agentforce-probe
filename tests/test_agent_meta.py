"""agent_meta.resolve_agent: BotDefinition type classification.

sfcli.query_soql is monkeypatched so no org is contacted. Covers internal vs
external classification, the MasterLabel fallback, the BotUserId heuristic, and
the not-found error.
"""

import pytest

from agentforce_probe import agent_meta


def test_resolve_external_copilot(monkeypatch):
    monkeypatch.setattr(
        agent_meta.sfcli,
        "query_soql",
        lambda org, soql, **k: [
            {"Id": "0Xx1", "DeveloperName": "Support", "Type": "ExternalCopilot", "BotUserId": "005"}
        ],
    )
    meta = agent_meta.resolve_agent("org", "Support")
    assert meta["is_internal"] is False
    assert meta["id"] == "0Xx1"


def test_resolve_internal_copilot(monkeypatch):
    monkeypatch.setattr(
        agent_meta.sfcli,
        "query_soql",
        lambda org, soql, **k: [
            {"Id": "0Xx2", "DeveloperName": "Helpdesk", "Type": "InternalCopilot", "BotUserId": None}
        ],
    )
    meta = agent_meta.resolve_agent("org", "Helpdesk")
    assert meta["is_internal"] is True


def test_resolve_employee_agent_normalized(monkeypatch):
    # "Agentforce Employee Agent" -> AGENTFORCEEMPLOYEEAGENT after normalization.
    monkeypatch.setattr(
        agent_meta.sfcli,
        "query_soql",
        lambda org, soql, **k: [{"Id": "0Xx3", "DeveloperName": "Emp", "Type": "Agentforce Employee Agent"}],
    )
    assert agent_meta.resolve_agent("org", "Emp")["is_internal"] is True


def test_resolve_heuristic_null_botuser_is_internal(monkeypatch):
    # Unknown type + null BotUserId -> heuristic says internal.
    monkeypatch.setattr(
        agent_meta.sfcli,
        "query_soql",
        lambda org, soql, **k: [{"Id": "0Xx4", "DeveloperName": "Weird", "Type": "SomethingNew", "BotUserId": None}],
    )
    assert agent_meta.resolve_agent("org", "Weird")["is_internal"] is True


def test_resolve_masterlabel_fallback(monkeypatch):
    calls = {"n": 0}

    def query(org, soql, **k):
        calls["n"] += 1
        if calls["n"] == 1:  # DeveloperName query returns nothing
            return []
        return [
            {
                "Id": "0Xx5",
                "DeveloperName": "Dev",
                "MasterLabel": "My Label",
                "Type": "ExternalCopilot",
                "BotUserId": "005",
            }
        ]

    monkeypatch.setattr(agent_meta.sfcli, "query_soql", query)
    meta = agent_meta.resolve_agent("org", "My Label")
    assert meta["id"] == "0Xx5"
    assert calls["n"] == 2  # both queries ran


def test_resolve_not_found_raises(monkeypatch):
    monkeypatch.setattr(agent_meta.sfcli, "query_soql", lambda org, soql, **k: [])
    with pytest.raises(agent_meta.AgentMetaError, match="no BotDefinition"):
        agent_meta.resolve_agent("org", "Ghost")
