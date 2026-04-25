from proxy.loadbalancer import LoadBalancer


class TestLoadBalancer:
    def test_round_robin_cycles_urls(self):
        lb = LoadBalancer()
        urls = ["http://a", "http://b", "http://c"]
        results = [lb.pick_url("test", urls, "round_robin") for _ in range(6)]
        assert results == ["http://a", "http://b", "http://c", "http://a", "http://b", "http://c"]

    def test_random_selects_from_list(self):
        lb = LoadBalancer()
        urls = ["http://a", "http://b"]
        results = set(lb.pick_url("test", urls, "random") for _ in range(50))
        assert results == {"http://a", "http://b"}

    def test_least_latency_picks_fastest(self):
        lb = LoadBalancer()
        urls = ["http://slow", "http://fast"]
        lb.record_latency("http://slow", 500)
        lb.record_latency("http://fast", 50)
        assert lb.pick_url("test", urls, "least_latency") == "http://fast"

    def test_least_latency_prefers_untested(self):
        lb = LoadBalancer()
        urls = ["http://tested", "http://new"]
        lb.record_latency("http://tested", 100)
        assert lb.pick_url("test", urls, "least_latency") == "http://new"

    def test_single_url_returns_directly(self):
        lb = LoadBalancer()
        assert lb.pick_url("test", ["http://only"], "round_robin") == "http://only"

    def test_get_stats(self):
        lb = LoadBalancer()
        lb.record_latency("http://a", 100)
        lb.record_latency("http://a", 200)
        stats = lb.get_stats()
        assert stats["http://a"]["count"] == 2
        assert stats["http://a"]["avg_latency_ms"] == 150.0
