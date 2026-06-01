"""Resolve agent metadata from the org: BotDefinition.Type + Id.

Type distinguishes ExternalCopilot (sf agent test works) from InternalCopilot
(employee agent — must use the headless Agent API). The BotDefinition Id
(0Xx...) is what the Agent API session endpoint needs.
"""

from . import sfcli


class AgentMetaError(RuntimeError):
    pass


# Common variants Salesforce uses for employee/internal agents.
INTERNAL_TYPES = {"INTERNALCOPILOT", "EMPLOYEEAGENT", "AGENTFORCEEMPLOYEEAGENT"}
EXTERNAL_TYPES = {"EXTERNALCOPILOT", "BOT", "AGENTFORCESERVICEAGENT"}


def resolve_agent(org, agent_name):
    """Query BotDefinition by DeveloperName. Returns dict with id/type/is_internal."""
    soql = (
        "SELECT Id, DeveloperName, MasterLabel, Type, BotUserId FROM BotDefinition WHERE DeveloperName = '{}'".format(
            agent_name.replace("'", "")
        )
    )
    records = sfcli.query_soql(org, soql)
    if not records:
        # try MasterLabel fallback
        soql2 = (
            "SELECT Id, DeveloperName, MasterLabel, Type, BotUserId FROM BotDefinition WHERE MasterLabel = '{}'".format(
                agent_name.replace("'", "")
            )
        )
        records = sfcli.query_soql(org, soql2)
    if not records:
        raise AgentMetaError(f"no BotDefinition found for '{agent_name}' (tried DeveloperName and MasterLabel)")
    rec = records[0]
    raw_type = (rec.get("Type") or "").strip()
    norm = raw_type.upper().replace(" ", "").replace("_", "")
    if norm in INTERNAL_TYPES:
        is_internal = True
    elif norm in EXTERNAL_TYPES:
        is_internal = False
    else:
        # Heuristic fallback: null BotUserId strongly implies an employee agent.
        is_internal = rec.get("BotUserId") in (None, "", "null")
    return {
        "id": rec.get("Id"),
        "developer_name": rec.get("DeveloperName"),
        "label": rec.get("MasterLabel"),
        "type": raw_type or "(unknown)",
        "bot_user_id": rec.get("BotUserId"),
        "is_internal": is_internal,
    }
