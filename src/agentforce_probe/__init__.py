"""agentforce-probe: a local, privacy-first CLI to run automated tests against
Salesforce Agentforce agents and score them into evidence.

Privacy-first, fully local. The only outbound network calls are to the target
Salesforce org and (optionally, Internal path only) the configured judge LLM.
Secrets are never exfiltrated, printed, logged, or written to evidence.
"""

__version__ = "0.1.1"
