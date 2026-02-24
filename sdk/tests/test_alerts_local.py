"""Tests for client-side alert rules, MetricAggregator, and AlertManager."""

import time
import pytest

from agentlens.alerts import (
    AlertRule,
    AlertManager,
    MetricAggregator,
    Alert,
    Severity,
    Condition,
)


# ── MetricAggregator ────────────────────────────────────────────────


class TestMetricAggregator:
    def test_record_and_event_count(self):
        agg = MetricAggregator(window_seconds=60)
        agg.record({"duration_ms": 100})
        agg.record({"duration_ms": 200})
        assert agg.get_metric("event_count") == 2.0

    def test_empty_returns_zero(self):
        agg = MetricAggregator(window_seconds=60)
        assert agg.get_metric("event_count") == 0.0
        assert agg.get_metric("error_rate") == 0.0
        assert agg.get_metric("total_tokens") == 0.0
        assert agg.get_metric("total_cost") == 0.0
        assert agg.get_metric("latency_p95") == 0.0
        assert agg.get_metric("avg_duration_ms") == 0.0

    def test_heartbeat_empty_returns_inf(self):
        agg = MetricAggregator(window_seconds=60)
        assert agg.get_metric("heartbeat") == float("inf")

    def test_heartbeat_with_events(self):
        agg = MetricAggregator(window_seconds=60)
        agg.record({"timestamp": time.time()})
        val = agg.get_metric("heartbeat")
        assert val < 1.0  # Should be very close to 0

    def test_error_rate(self):
        agg = MetricAggregator(window_seconds=60)
        agg.record({"error": True})
        agg.record({"error": False})
        agg.record({"error": True})
        agg.record({})  # no error key = not an error
        assert agg.get_metric("error_rate") == 0.5

    def test_error_rate_all_errors(self):
        agg = MetricAggregator(window_seconds=60)
        agg.record({"error": True})
        agg.record({"error": True})
        assert agg.get_metric("error_rate") == 1.0

    def test_total_tokens(self):
        agg = MetricAggregator(window_seconds=60)
        agg.record({"tokens_in": 100, "tokens_out": 50})
        agg.record({"tokens_in": 200, "tokens_out": 75})
        assert agg.get_metric("total_tokens") == 425.0

    def test_total_cost(self):
        agg = MetricAggregator(window_seconds=60)
        agg.record({"cost": 0.5})
        agg.record({"cost": 1.2})
        agg.record({})  # no cost
        assert abs(agg.get_metric("total_cost") - 1.7) < 0.001

    def test_avg_duration(self):
        agg = MetricAggregator(window_seconds=60)
        agg.record({"duration_ms": 100})
        agg.record({"duration_ms": 200})
        agg.record({"duration_ms": 300})
        assert agg.get_metric("avg_duration_ms") == 200.0

    def test_avg_duration_skips_none(self):
        agg = MetricAggregator(window_seconds=60)
        agg.record({"duration_ms": 100})
        agg.record({})  # no duration_ms
        agg.record({"duration_ms": 300})
        assert agg.get_metric("avg_duration_ms") == 200.0

    def test_latency_p50(self):
        agg = MetricAggregator(window_seconds=60)
        for d in [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]:
            agg.record({"duration_ms": d})
        val = agg.get_metric("latency_p50")
        assert 50 <= val <= 60  # median area

    def test_latency_p95(self):
        agg = MetricAggregator(window_seconds=60)
        for d in range(1, 101):
            agg.record({"duration_ms": float(d)})
        val = agg.get_metric("latency_p95")
        assert val > 90  # Should be around 95

    def test_latency_p99(self):
        agg = MetricAggregator(window_seconds=60)
        for d in range(1, 101):
            agg.record({"duration_ms": float(d)})
        val = agg.get_metric("latency_p99")
        assert val > 95

    def test_latency_single_event(self):
        agg = MetricAggregator(window_seconds=60)
        agg.record({"duration_ms": 42.0})
        assert agg.get_metric("latency_p50") == 42.0
        assert agg.get_metric("latency_p95") == 42.0
        assert agg.get_metric("latency_p99") == 42.0

    def test_agent_filter(self):
        agg = MetricAggregator(window_seconds=60)
        agg.record({"agent_name": "alpha", "tokens_in": 100, "tokens_out": 0})
        agg.record({"agent_name": "beta", "tokens_in": 200, "tokens_out": 0})
        agg.record({"agent_name": "alpha", "tokens_in": 50, "tokens_out": 0})

        assert agg.get_metric("total_tokens", agent_filter="alpha") == 150.0
        assert agg.get_metric("total_tokens", agent_filter="beta") == 200.0
        assert agg.get_metric("event_count", agent_filter="alpha") == 2.0

    def test_eviction(self):
        agg = MetricAggregator(window_seconds=1)
        agg.record({"timestamp": time.time() - 5, "duration_ms": 999})
        agg.record({"timestamp": time.time(), "duration_ms": 100})
        # The old event should be evicted
        assert agg.get_metric("event_count") == 1.0

    def test_clear(self):
        agg = MetricAggregator(window_seconds=60)
        agg.record({"duration_ms": 100})
        agg.clear()
        assert agg.get_metric("event_count") == 0.0

    def test_unknown_metric_raises(self):
        agg = MetricAggregator(window_seconds=60)
        agg.record({"duration_ms": 100})
        with pytest.raises(ValueError, match="Unknown metric"):
            agg.get_metric("nonexistent_metric")

    def test_window_property(self):
        agg = MetricAggregator(window_seconds=120)
        assert agg.window_seconds == 120


# ── AlertRule ────────────────────────────────────────────────────────


class TestAlertRule:
    def test_defaults(self):
        rule = AlertRule(
            name="test",
            metric="event_count",
            condition=Condition.GREATER_THAN,
            threshold=10,
        )
        assert rule.window_seconds == 300
        assert rule.cooldown_seconds == 900
        assert rule.severity == Severity.WARNING
        assert rule.enabled is True
        assert rule.agent_filter is None

    def test_custom_fields(self):
        rule = AlertRule(
            name="custom",
            metric="latency_p95",
            condition=Condition.GREATER_THAN,
            threshold=5000,
            window_seconds=60,
            cooldown_seconds=120,
            severity=Severity.CRITICAL,
            enabled=False,
            agent_filter="my-agent",
        )
        assert rule.window_seconds == 60
        assert rule.cooldown_seconds == 120
        assert rule.severity == Severity.CRITICAL
        assert rule.enabled is False
        assert rule.agent_filter == "my-agent"


# ── Alert ────────────────────────────────────────────────────────────


class TestAlert:
    def test_to_dict(self):
        alert = Alert(
            rule_name="test",
            metric="error_rate",
            value=0.15,
            threshold=0.10,
            severity=Severity.WARNING,
            message="Test alert",
            timestamp=1234567890.0,
            agent_name="alpha",
        )
        d = alert.to_dict()
        assert d["rule_name"] == "test"
        assert d["metric"] == "error_rate"
        assert d["value"] == 0.15
        assert d["threshold"] == 0.10
        assert d["severity"] == "warning"
        assert d["message"] == "Test alert"
        assert d["timestamp"] == 1234567890.0
        assert d["agent_name"] == "alpha"

    def test_to_dict_no_agent(self):
        alert = Alert(
            rule_name="test",
            metric="event_count",
            value=100,
            threshold=50,
            severity=Severity.INFO,
            message="Test",
        )
        d = alert.to_dict()
        assert d["agent_name"] is None


# ── AlertManager ─────────────────────────────────────────────────────


class TestAlertManager:
    def test_empty_manager(self):
        manager = AlertManager()
        assert manager.get_rules() == []
        assert manager.evaluate() == []

    def test_add_rule(self):
        manager = AlertManager()
        rule = AlertRule(
            name="high_tokens",
            metric="total_tokens",
            condition=Condition.GREATER_THAN,
            threshold=1000,
        )
        manager.add_rule(rule)
        assert len(manager.get_rules()) == 1
        assert manager.get_rules()[0].name == "high_tokens"

    def test_remove_rule(self):
        manager = AlertManager()
        rule = AlertRule(name="r1", metric="event_count", condition=Condition.GREATER_THAN, threshold=10)
        manager.add_rule(rule)
        assert manager.remove_rule("r1") is True
        assert manager.remove_rule("r1") is False
        assert len(manager.get_rules()) == 0

    def test_constructor_with_rules(self):
        rules = [
            AlertRule(name="r1", metric="event_count", condition=Condition.GREATER_THAN, threshold=5),
            AlertRule(name="r2", metric="error_rate", condition=Condition.GREATER_THAN, threshold=0.1),
        ]
        manager = AlertManager(rules)
        assert len(manager.get_rules()) == 2

    def test_greater_than_fires(self):
        rule = AlertRule(
            name="high_tokens",
            metric="total_tokens",
            condition=Condition.GREATER_THAN,
            threshold=100,
            window_seconds=60,
            cooldown_seconds=0,
        )
        manager = AlertManager([rule])

        # Below threshold
        alerts = manager.process_event({"tokens_in": 30, "tokens_out": 20})
        assert len(alerts) == 0

        # Above threshold
        alerts = manager.process_event({"tokens_in": 50, "tokens_out": 50})
        assert len(alerts) == 1
        assert alerts[0].rule_name == "high_tokens"
        assert alerts[0].value > 100

    def test_less_than_fires(self):
        rule = AlertRule(
            name="low_events",
            metric="event_count",
            condition=Condition.LESS_THAN,
            threshold=5,
            window_seconds=60,
            cooldown_seconds=0,
        )
        manager = AlertManager([rule])
        alerts = manager.process_event({"duration_ms": 100})
        assert len(alerts) == 1  # Only 1 event, which is < 5

    def test_equals_fires(self):
        rule = AlertRule(
            name="exact_count",
            metric="event_count",
            condition=Condition.EQUALS,
            threshold=2,
            window_seconds=60,
            cooldown_seconds=0,
        )
        manager = AlertManager([rule])
        manager.process_event({})
        alerts = manager.process_event({})
        assert len(alerts) == 1

    def test_not_equals_fires(self):
        rule = AlertRule(
            name="not_zero",
            metric="error_rate",
            condition=Condition.NOT_EQUALS,
            threshold=0,
            window_seconds=60,
            cooldown_seconds=0,
        )
        manager = AlertManager([rule])
        alerts = manager.process_event({"error": True})
        assert len(alerts) == 1

    def test_absent_condition(self):
        rule = AlertRule(
            name="no_heartbeat",
            metric="heartbeat",
            condition=Condition.ABSENT,
            threshold=2,  # 2 seconds
            window_seconds=60,
            cooldown_seconds=0,
        )
        manager = AlertManager([rule])
        # No events → heartbeat = infinity → should fire
        alerts = manager.evaluate()
        assert len(alerts) == 1
        assert alerts[0].metric == "heartbeat"

    def test_cooldown_prevents_repeat(self):
        rule = AlertRule(
            name="test",
            metric="event_count",
            condition=Condition.GREATER_THAN,
            threshold=0,
            window_seconds=60,
            cooldown_seconds=9999,
        )
        manager = AlertManager([rule])

        alerts1 = manager.process_event({})
        assert len(alerts1) == 1

        # Same evaluation again — should be in cooldown
        alerts2 = manager.process_event({})
        assert len(alerts2) == 0

    def test_cooldown_zero_allows_repeat(self):
        rule = AlertRule(
            name="test",
            metric="event_count",
            condition=Condition.GREATER_THAN,
            threshold=0,
            window_seconds=60,
            cooldown_seconds=0,
        )
        manager = AlertManager([rule])

        alerts1 = manager.process_event({})
        assert len(alerts1) == 1

        alerts2 = manager.process_event({})
        assert len(alerts2) == 1

    def test_disabled_rule_ignored(self):
        rule = AlertRule(
            name="disabled",
            metric="event_count",
            condition=Condition.GREATER_THAN,
            threshold=0,
            window_seconds=60,
            cooldown_seconds=0,
            enabled=False,
        )
        manager = AlertManager([rule])
        alerts = manager.process_event({})
        assert len(alerts) == 0

    def test_agent_filter(self):
        rule = AlertRule(
            name="alpha_tokens",
            metric="total_tokens",
            condition=Condition.GREATER_THAN,
            threshold=50,
            window_seconds=60,
            cooldown_seconds=0,
            agent_filter="alpha",
        )
        manager = AlertManager([rule])

        # Event from beta — should not trigger
        manager.process_event({"agent_name": "beta", "tokens_in": 100, "tokens_out": 0})
        alerts = manager.evaluate()
        assert len(alerts) == 0

        # Event from alpha — should trigger
        alerts = manager.process_event({"agent_name": "alpha", "tokens_in": 100, "tokens_out": 0})
        assert len(alerts) == 1

    def test_callback_fires(self):
        received = []
        rule = AlertRule(
            name="test",
            metric="event_count",
            condition=Condition.GREATER_THAN,
            threshold=0,
            window_seconds=60,
            cooldown_seconds=0,
        )
        manager = AlertManager([rule])
        manager.on_alert(lambda a: received.append(a))

        manager.process_event({})
        assert len(received) == 1
        assert received[0].rule_name == "test"

    def test_callback_exception_doesnt_break(self):
        def bad_callback(alert):
            raise RuntimeError("boom")

        rule = AlertRule(
            name="test",
            metric="event_count",
            condition=Condition.GREATER_THAN,
            threshold=0,
            window_seconds=60,
            cooldown_seconds=0,
        )
        manager = AlertManager([rule])
        manager.on_alert(bad_callback)

        # Should not raise
        alerts = manager.process_event({})
        assert len(alerts) == 1

    def test_alert_history(self):
        rule = AlertRule(
            name="test",
            metric="event_count",
            condition=Condition.GREATER_THAN,
            threshold=0,
            window_seconds=60,
            cooldown_seconds=0,
        )
        manager = AlertManager([rule])
        manager.process_event({})
        manager.process_event({})

        history = manager.get_alert_history()
        assert len(history) == 2

    def test_alert_history_limit(self):
        rule = AlertRule(
            name="test",
            metric="event_count",
            condition=Condition.GREATER_THAN,
            threshold=0,
            window_seconds=60,
            cooldown_seconds=0,
        )
        manager = AlertManager([rule])
        for _ in range(10):
            manager.process_event({})

        assert len(manager.get_alert_history(limit=3)) == 3

    def test_clear_cooldowns(self):
        rule = AlertRule(
            name="test",
            metric="event_count",
            condition=Condition.GREATER_THAN,
            threshold=0,
            window_seconds=60,
            cooldown_seconds=9999,
        )
        manager = AlertManager([rule])

        manager.process_event({})
        assert len(manager.process_event({})) == 0  # cooldown

        manager.clear_cooldowns()
        assert len(manager.process_event({})) == 1  # fires again

    def test_clear_history(self):
        rule = AlertRule(
            name="test",
            metric="event_count",
            condition=Condition.GREATER_THAN,
            threshold=0,
            window_seconds=60,
            cooldown_seconds=0,
        )
        manager = AlertManager([rule])
        manager.process_event({})
        assert len(manager.get_alert_history()) == 1

        manager.clear_history()
        assert len(manager.get_alert_history()) == 0

    def test_reset(self):
        rule = AlertRule(
            name="test",
            metric="event_count",
            condition=Condition.GREATER_THAN,
            threshold=0,
            window_seconds=60,
            cooldown_seconds=9999,
        )
        manager = AlertManager([rule])
        manager.process_event({})

        manager.reset()
        assert len(manager.get_alert_history()) == 0
        # After reset, cooldown is cleared and aggregator is empty
        # event_count = 0, not > 0, so no alert
        alerts = manager.evaluate()
        assert len(alerts) == 0

    def test_multiple_rules_fire_independently(self):
        r1 = AlertRule(
            name="high_tokens",
            metric="total_tokens",
            condition=Condition.GREATER_THAN,
            threshold=50,
            window_seconds=60,
            cooldown_seconds=0,
        )
        r2 = AlertRule(
            name="high_errors",
            metric="error_rate",
            condition=Condition.GREATER_THAN,
            threshold=0.5,
            window_seconds=60,
            cooldown_seconds=0,
        )
        manager = AlertManager([r1, r2])

        alerts = manager.process_event({"tokens_in": 100, "tokens_out": 0, "error": True})
        # r1: total_tokens=100 > 50 → fires
        # r2: error_rate=1.0 > 0.5 → fires
        assert len(alerts) == 2
        names = {a.rule_name for a in alerts}
        assert "high_tokens" in names
        assert "high_errors" in names

    def test_different_windows(self):
        r_short = AlertRule(
            name="short",
            metric="event_count",
            condition=Condition.GREATER_THAN,
            threshold=0,
            window_seconds=1,
            cooldown_seconds=0,
        )
        r_long = AlertRule(
            name="long",
            metric="event_count",
            condition=Condition.GREATER_THAN,
            threshold=0,
            window_seconds=3600,
            cooldown_seconds=0,
        )
        manager = AlertManager([r_short, r_long])
        manager.process_event({"timestamp": time.time() - 10})

        # Short window should have evicted the old event
        # But long window should still have it
        alerts = manager.evaluate()
        names = {a.rule_name for a in alerts}
        assert "long" in names

    def test_alert_message_format(self):
        rule = AlertRule(
            name="latency_spike",
            metric="latency_p95",
            condition=Condition.GREATER_THAN,
            threshold=5000,
            severity=Severity.CRITICAL,
            window_seconds=60,
            cooldown_seconds=0,
        )
        manager = AlertManager([rule])
        alerts = manager.process_event({"duration_ms": 7000})
        assert len(alerts) == 1
        assert "CRITICAL" in alerts[0].message
        assert "latency_spike" in alerts[0].message
        assert "latency_p95" in alerts[0].message

    def test_alert_severity_levels(self):
        for sev in [Severity.INFO, Severity.WARNING, Severity.CRITICAL]:
            rule = AlertRule(
                name=f"test_{sev.value}",
                metric="event_count",
                condition=Condition.GREATER_THAN,
                threshold=0,
                window_seconds=60,
                cooldown_seconds=0,
                severity=sev,
            )
            manager = AlertManager([rule])
            alerts = manager.process_event({})
            assert alerts[0].severity == sev

    def test_replace_rule(self):
        rule1 = AlertRule(
            name="test",
            metric="event_count",
            condition=Condition.GREATER_THAN,
            threshold=100,
            window_seconds=60,
            cooldown_seconds=0,
        )
        rule2 = AlertRule(
            name="test",
            metric="event_count",
            condition=Condition.GREATER_THAN,
            threshold=0,  # Lower threshold
            window_seconds=60,
            cooldown_seconds=0,
        )
        manager = AlertManager([rule1])

        # With high threshold, 1 event shouldn't fire
        alerts = manager.process_event({})
        assert len(alerts) == 0

        # Replace with lower threshold
        manager.add_rule(rule2)
        alerts = manager.process_event({})
        assert len(alerts) == 1


# ── Condition checks ─────────────────────────────────────────────────


class TestConditionChecks:
    def test_greater_than(self):
        assert AlertManager._check_condition(Condition.GREATER_THAN, 10, 5) is True
        assert AlertManager._check_condition(Condition.GREATER_THAN, 5, 10) is False
        assert AlertManager._check_condition(Condition.GREATER_THAN, 5, 5) is False

    def test_less_than(self):
        assert AlertManager._check_condition(Condition.LESS_THAN, 3, 5) is True
        assert AlertManager._check_condition(Condition.LESS_THAN, 5, 3) is False
        assert AlertManager._check_condition(Condition.LESS_THAN, 5, 5) is False

    def test_equals(self):
        assert AlertManager._check_condition(Condition.EQUALS, 5, 5) is True
        assert AlertManager._check_condition(Condition.EQUALS, 5, 6) is False

    def test_not_equals(self):
        assert AlertManager._check_condition(Condition.NOT_EQUALS, 5, 6) is True
        assert AlertManager._check_condition(Condition.NOT_EQUALS, 5, 5) is False

    def test_absent(self):
        assert AlertManager._check_condition(Condition.ABSENT, 10, 5) is True
        assert AlertManager._check_condition(Condition.ABSENT, 3, 5) is False

    def test_rate_change(self):
        assert AlertManager._check_condition(Condition.RATE_CHANGE, 25, 20) is True
        assert AlertManager._check_condition(Condition.RATE_CHANGE, -25, 20) is True
        assert AlertManager._check_condition(Condition.RATE_CHANGE, 10, 20) is False


# ── Percentile ───────────────────────────────────────────────────────


class TestPercentile:
    def test_empty(self):
        assert MetricAggregator._percentile([], 50) == 0.0

    def test_single_value(self):
        assert MetricAggregator._percentile([42.0], 50) == 42.0
        assert MetricAggregator._percentile([42.0], 95) == 42.0

    def test_two_values(self):
        # p50 of [10, 20] = 15 (midpoint)
        assert MetricAggregator._percentile([10.0, 20.0], 50) == 15.0

    def test_p0(self):
        assert MetricAggregator._percentile([10.0, 20.0, 30.0], 0) == 10.0

    def test_p100(self):
        assert MetricAggregator._percentile([10.0, 20.0, 30.0], 100) == 30.0


# ── Imports ──────────────────────────────────────────────────────────


class TestImports:
    def test_import_from_package(self):
        from agentlens import AlertRule, AlertManager, MetricAggregator, Alert, Severity, Condition
        assert AlertRule is not None
        assert AlertManager is not None
        assert MetricAggregator is not None
        assert Alert is not None
        assert Severity is not None
        assert Condition is not None
