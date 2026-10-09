# Fabric User Data Functions item: udf_goldenrecord_steward
# Called from the Power BI steward report through translytical task flows (data function buttons).
# Each function records the steward's action, with their verified Entra identity, in the Fabric SQL
# database `sqldb_goldenrecord_steward`. nb_05_apply_steward_inbox turns new rows into versioned
# rule-library changes. Functions return a string, as translytical task flows require.
#
# Setup: add a connection to the SQL database with alias "stewarddb" (Manage connections).

import datetime

import fabric.functions as fn

udf = fn.UserDataFunctions()

VALID_PATTERN_DECISIONS = {"approve", "reject"}


def _who(ctx: fn.UserDataFunctionContext) -> str:
    return ctx.executing_user.get("PreferredUsername") or ctx.executing_user.get("Oid")


@udf.connection(argName="stewarddb", alias="stewarddb")
@udf.context(argName="ctx")
@udf.function()
def decide_pattern(stewarddb: fn.FabricSqlConnection, ctx: fn.UserDataFunctionContext, patternId: str,
                   decision: str, canonical: str = "", note: str = "") -> str:
    """Approve or reject one root-cause pattern (applies to every record in it, now and in future loads)."""
    if decision not in VALID_PATTERN_DECISIONS:
        raise fn.UserThrownError("Decision must be 'approve' or 'reject'.", {"decision": decision})
    conn = stewarddb.connect()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO dbo.pattern_decisions_inbox (pattern_id, decision, canonical, note, reviewer, decided_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (patternId, decision, canonical or None, note, _who(ctx), datetime.datetime.utcnow()))
    conn.commit()
    cursor.close()
    conn.close()
    return f"{decision.capitalize()}d pattern {patternId}. It applies to all matching records from the next run."


@udf.connection(argName="stewarddb", alias="stewarddb")
@udf.context(argName="ctx")
@udf.function()
def unmerge_record(stewarddb: fn.FabricSqlConnection, ctx: fn.UserDataFunctionContext, recordKey: str,
                   note: str = "") -> str:
    """Detach a source record from its golden record (adds versioned cannot-links)."""
    if ":" not in recordKey:
        raise fn.UserThrownError("Record key looks like ERP_A:0000100001.", {"recordKey": recordKey})
    conn = stewarddb.connect()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO dbo.unmerge_inbox (record_key, note, reviewer, decided_at) VALUES (?, ?, ?, ?)",
                   (recordKey, note, _who(ctx), datetime.datetime.utcnow()))
    conn.commit()
    cursor.close()
    conn.close()
    return f"{recordKey} will be separated from its golden record on the next run."


@udf.connection(argName="stewarddb", alias="stewarddb")
@udf.context(argName="ctx")
@udf.function()
def request_rule(stewarddb: fn.FabricSqlConnection, ctx: fn.UserDataFunctionContext, ruleText: str,
                 accept: bool = False, override: bool = False) -> str:
    """Submit a plain-English rule. First call previews its impact; accept=True adds it in shadow mode."""
    if len(ruleText.strip()) < 10:
        raise fn.UserThrownError("Describe the rule in a sentence, naming the field and the condition.", {})
    conn = stewarddb.connect()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO dbo.rule_requests_inbox (rule_text, accept, override, reviewer, requested_at) "
        "VALUES (?, ?, ?, ?, ?)", (ruleText.strip(), int(accept), int(override), _who(ctx), datetime.datetime.utcnow()))
    conn.commit()
    cursor.close()
    conn.close()
    return ("Rule submitted for preview. Its impact by source appears on the Rule studio page."
            if not accept else "Rule accepted in shadow mode: it flags records but quarantines nothing until promoted.")
