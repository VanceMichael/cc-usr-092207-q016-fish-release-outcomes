"""读取并检查共享的领域资料。

校验重点对应领域原则：
- 亲本→检疫→标记→运输→现场计数→放流→河段水文与后续采样必须形成连续血缘；
- 原始观察只追加不修改，计数纠正、标签脱落、重捕、异常死亡、方案换版只产生新记录或新分析；
- 归属判定（含混合样本）必须给出方法与置信度；
- 指标必须能由原始观察复算，年度决策只能引用 current 分析。
"""

import json
from pathlib import Path

REQUIRED = {
    "domain", "version", "sample_id", "actors", "facts", "constraints",
    "custody_chain", "reaches", "batches", "releases",
    "observations", "origin_assignments", "analyses", "decisions",
}

CHAIN_STAGES = [
    "broodstock", "breeding_quarantine", "tagging", "transport",
    "on_site_count", "release", "post_release_sampling",
]

STAGE_RESPONSIBILITY = {
    "broodstock": "broodstock",
    "breeding_quarantine": "breeding_quarantine",
    "tagging": "tagging",
    "transport": "transport",
    "on_site_count": "on_site_count",
    "release": "release_execution",
    "post_release_sampling": "field_sampling",
}

# 分析输入中出现某类观察时，分析必须显式声明对应调整，禁止静默修正。
OBSERVED_ADJUSTMENT = {
    "recapture": "recapture_dedup",
    "count_correction": "count_correction",
    "abnormal_mortality": "abnormal_mortality",
    "mixed_sample": "mixed_sample_probabilistic",
}

# 各观察类型的证据归属方必须具备的职责。
OBSERVATION_RESPONSIBILITY = {
    "hydrology": "field_sampling",
    "capture": "field_sampling",
    "recapture": "field_sampling",
    "mixed_sample": "field_sampling",
    "field_finding": "independent_evidence",
    "on_site_count": "on_site_count",
    "count_correction": "on_site_count",
    "abnormal_mortality": "independent_evidence",
}


def load_domain(path: Path) -> dict:
    """返回字段完整、引用闭合且符合领域约束的业务资料。"""
    value = json.loads(path.read_text(encoding="utf-8"))
    validate_domain(value)
    return value


def validate_domain(value: dict) -> None:
    missing = REQUIRED - value.keys()
    if missing:
        raise ValueError(f"共享资料缺少必要字段: {sorted(missing)}")
    if value["version"] < 2:
        raise ValueError("共享资料版本过低，连续血缘结构需要 version >= 2")
    if len(value["actors"]) < 4 or len(value["facts"]) < 2 or len(value["constraints"]) < 2:
        raise ValueError("共享资料内容不完整")

    actors = {a["id"]: a for a in value["actors"]}
    if len(actors) != len(value["actors"]):
        raise ValueError("参与方标识重复")

    reaches = {r["id"]: r for r in value["reaches"]}
    broodstock = {b["id"]: b for b in value.get("broodstock", [])}
    batches = {b["id"]: b for b in value["batches"]}
    containers = {c["id"]: c for c in value.get("transport_containers", [])}
    observations = {o["id"]: o for o in value["observations"]}
    if len(observations) != len(value["observations"]):
        raise ValueError("原始观察标识重复")

    analyses = {a["id"]: a for a in value["analyses"]}
    if len(analyses) != len(value["analyses"]):
        raise ValueError("分析标识重复")

    _validate_custody_chain(value["custody_chain"], actors)
    _validate_batches(batches, broodstock)
    _validate_containers(containers, batches)
    _validate_releases(value["releases"], batches, containers, reaches, observations)
    _validate_observations(observations, actors, reaches)
    _validate_assignments(value["origin_assignments"], observations, actors, analyses, batches)
    _validate_analyses(value["analyses"], observations, actors, value["origin_assignments"])
    _validate_natural_spawning(value.get("natural_spawning_evidence"), observations, actors)
    _validate_decisions(value["decisions"], analyses, actors)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _validate_custody_chain(chain: list, actors: dict) -> None:
    stages = [step["stage"] for step in chain]
    _require(
        stages[:len(CHAIN_STAGES)] == CHAIN_STAGES,
        f"血缘链阶段必须连续覆盖 {CHAIN_STAGES}",
    )
    for step in chain:
        actor = actors.get(step["actor"])
        _require(actor is not None, f"血缘链引用了未知参与方: {step['actor']}")
        needed = STAGE_RESPONSIBILITY[step["stage"]]
        _require(
            needed in actor["responsibilities"],
            f"血缘链阶段 {step['stage']} 由不具备 {needed} 职责的参与方承担",
        )


def _validate_batches(batches: dict, broodstock: dict) -> None:
    for batch in batches.values():
        _require(batch["quarantine_passed"], f"批次 {batch['id']} 未通过检疫不得放流")
        _require(len(batch["parent_ids"]) >= 2, f"批次 {batch['id']} 缺少亲本血缘")
        for parent_id in batch["parent_ids"]:
            _require(parent_id in broodstock, f"批次 {batch['id']} 引用未知亲本: {parent_id}")


def _validate_containers(containers: dict, batches: dict) -> None:
    for container in containers.values():
        _require(container["batch_id"] in batches, f"容器 {container['id']} 引用未知批次")
        doa = container.get("doa_on_arrival", 0)
        _require(doa <= container["loaded_count"], f"容器 {container['id']} 死亡数超过装载数")


def _validate_releases(releases: list, batches: dict, containers: dict, reaches: dict, observations: dict) -> None:
    for release in releases:
        _require(release["batch_id"] in batches, f"放流 {release['id']} 引用未知批次")
        _require(release["reach_id"] in reaches, f"放流 {release['id']} 引用未知河段")
        for container_id in release.get("container_ids", []):
            _require(container_id in containers, f"放流 {release['id']} 引用未知运输容器")
        hydrology = release.get("hydrology")
        if hydrology:
            for obs_id in hydrology.get("source_observation_ids", []):
                _require(obs_id in observations, f"放流 {release['id']} 水文引用未知观察: {obs_id}")


def _validate_observations(observations: dict, actors: dict, reaches: dict) -> None:
    for obs in observations.values():
        _require(obs.get("immutable") is True, f"观察 {obs['id']} 必须标记为不可变原始记录")
        actor = actors.get(obs["actor"])
        _require(actor is not None, f"观察 {obs['id']} 引用未知参与方")
        if "reach_id" in obs:
            _require(obs["reach_id"] in reaches, f"观察 {obs['id']} 引用未知河段")
        needed = OBSERVATION_RESPONSIBILITY.get(obs["type"])
        if needed:
            _require(
                needed in actor["responsibilities"],
                f"观察 {obs['id']} 类型 {obs['type']} 不属于该参与方职责",
            )
        if "corrects" in obs:
            original = observations.get(obs["corrects"])
            _require(original is not None, f"纠正记录 {obs['id']} 指向不存在的原始观察")
            _require(
                obs["corrects"] != obs["id"] and original.get("immutable") is True,
                f"纠正记录 {obs['id']} 只能追加在锁定的原始观察之后",
            )
            _require(
                obs["recorded_at"] >= original["recorded_at"],
                f"纠正记录 {obs['id']} 时间早于原始观察，禁止回溯改写",
            )


def _validate_assignments(assignments: list, observations: dict, actors: dict, analyses: dict, batches: dict) -> None:
    captured = {o["id"] for o in observations.values() if o["type"] in ("capture", "mixed_sample")}
    assigned = {a["observation_id"] for a in assignments}
    unassigned = captured - assigned
    _require(not unassigned, f"再发现观察缺少来源判定: {sorted(unassigned)}")

    for assignment in assignments:
        obs = observations.get(assignment["observation_id"])
        _require(obs is not None, f"归属判定 {assignment['id']} 引用未知观察")
        analyst = actors.get(assignment["analyst"])
        _require(analyst is not None, f"归属判定 {assignment['id']} 引用未知分析人员")
        _require(
            "origin_assignment" in analyst["responsibilities"],
            f"归属判定 {assignment['id']} 必须由具备来源判定职责的人员出具",
        )
        _require(assignment["analysis_id"] in analyses, f"归属判定 {assignment['id']} 引用未知分析")
        _require(0.0 <= assignment["confidence"] <= 1.0, f"归属判定 {assignment['id']} 置信度越界")
        if obs["type"] == "mixed_sample":
            _require(
                assignment["assignment"] == "undifferentiated",
                f"混合样本 {obs['id']} 不得给出逐尾确定归属",
            )
            _require(
                "credible_interval" in assignment and "posterior_hatchery" in assignment,
                f"混合样本归属 {assignment['id']} 必须给出后验与置信区间",
            )
        if assignment["assignment"] == "hatchery":
            _require(assignment.get("batch_id") in batches, f"归属 {assignment['id']} 指认人工来源但批次缺失")
        if assignment["assignment"] == "wild_natural":
            _require(
                assignment["confidence"] >= 0.95,
                f"归属 {assignment['id']} 判定自然来源的置信度低于0.95证据门槛",
            )


def _validate_analyses(analyses_list: list, observations: dict, actors: dict, assignments: list) -> None:
    current = [a for a in analyses_list if a["status"] == "current"]
    _require(len(current) == 1, "必须有且仅有一个 current 分析版本")

    by_id = {a["id"]: a for a in analyses_list}
    for analysis in analyses_list:
        producer = actors.get(analysis["produced_by"])
        _require(producer is not None, f"分析 {analysis['id']} 引用未知出具方")
        _require(
            "survival_dispersal_analysis" in producer["responsibilities"],
            f"分析 {analysis['id']} 必须由科研分析方出具",
        )
        input_ids = analysis["input_observation_ids"]
        _require(len(input_ids) == len(set(input_ids)), f"分析 {analysis['id']} 输入观察重复")
        for obs_id in input_ids:
            _require(obs_id in observations, f"分析 {analysis['id']} 引用未知观察: {obs_id}")

        adjustment_types = {item["type"] for item in analysis["adjustments"]}
        for obs_id in input_ids:
            needed = OBSERVED_ADJUSTMENT.get(observations[obs_id]["type"])
            if needed:
                _require(
                    needed in adjustment_types,
                    f"分析 {analysis['id']} 输入含 {observations[obs_id]['type']} 但缺少 {needed} 调整说明",
                )
        tag_loss = any(
            a.get("tag_loss_assumed") and a["analysis_id"] == analysis["id"]
            for a in assignments
        )
        if tag_loss:
            _require("tag_shed" in adjustment_types, f"分析 {analysis['id']} 使用标签脱落假设却未声明脱落校正")

        for metric in analysis.get("metrics", []):
            _require(metric["recomputable"] is True, f"指标 {metric['id']} 必须可复算")
            _require(metric["formula"].strip() != "", f"指标 {metric['id']} 缺少计算公式")
            outside = set(metric["inputs"]) - set(input_ids)
            _require(not outside, f"指标 {metric['id']} 使用了分析输入之外的观察: {sorted(outside)}")

        if "supersedes" in analysis:
            previous = by_id.get(analysis["supersedes"])
            _require(previous is not None, f"分析 {analysis['id']} 指向不存在的旧版本")
            _require(previous["status"] == "superseded", f"被取代分析 {previous['id']} 必须保留为 superseded")
            _require(
                analysis["analysis_version"] > previous["analysis_version"],
                f"分析 {analysis['id']} 版本号必须递增",
            )
            _require(
                bool(analysis.get("protocol_change_reason"))
                or analysis["monitoring_protocol_version"] == previous["monitoring_protocol_version"],
                f"分析 {analysis['id']} 监测方案换版必须说明原因",
            )


def _validate_natural_spawning(evidence: dict | None, observations: dict, actors: dict) -> None:
    if not evidence:
        return
    boundary = evidence["evidence_boundary"]
    _require(0.9 <= boundary["threshold_confidence"] <= 1.0, "自然产卵证据门槛应在[0.9,1]区间")
    for signal in evidence["signals"]:
        for obs_id in signal["observation_ids"]:
            obs = observations.get(obs_id)
            _require(obs is not None, f"自然产卵信号 {signal['id']} 引用未知观察")
            _require(
                "independent_evidence" in actors[obs["actor"]]["responsibilities"],
                f"自然产卵信号 {signal['id']} 必须由第三方独立证据支撑",
            )


def _validate_decisions(decisions: list, analyses: dict, actors: dict) -> None:
    for decision in decisions:
        analysis = analyses.get(decision["based_on_analysis"])
        _require(analysis is not None, f"决策 {decision['id']} 引用未知分析")
        _require(
            analysis["status"] == "current",
            f"决策 {decision['id']} 只能依据 current 分析，不得引用已废止版本",
        )
        decider = actors.get(decision["decided_by"])
        _require(decider is not None, f"决策 {decision['id']} 引用未知参与方")
        _require(
            "annual_decision" in decider["responsibilities"],
            f"决策 {decision['id']} 必须由流域保护决策方作出",
        )
        dimensions = {item["dimension"] for item in decision["adjustments"]}
        _require({"species", "quantity", "reach"} <= dimensions, f"决策 {decision['id']} 必须覆盖物种、数量、河段三个维度")
        _require(bool(decision["natural_spawning_declaration"].strip()), f"决策 {decision['id']} 必须声明自然产卵证据边界")
