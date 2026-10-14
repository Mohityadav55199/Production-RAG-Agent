"""
Client-address detection, pinned to a real capture from the production deployment
(browser -> Vercel -> Cloudflare -> Render). With the original defaults every visitor was identified as
Render's internal proxy, 10.27.213.240.
"""

from types import SimpleNamespace

import pytest

from app.config import get_settings
from app.utils.client_ip import client_address, describe

# Headers exactly as the Network check reported them. The visitor was 220.158.168.162; 65.2.144.101 is
# Vercel's server (what Cloudflare saw connecting), 172.71.198.72 a Cloudflare edge, 10.27.213.240 Render's LB.
PRODUCTION_HEADERS = {
    "x-forwarded-for": "220.158.168.162,65.2.144.101, 172.71.198.72, 10.27.213.240",
    "cf-connecting-ip": "65.2.144.101",
    "true-client-ip": "65.2.144.101",
    "forwarded": "for=220.158.168.162;host=production-rag-agent.onrender.com;proto=https",
    "x-forwarded-proto": "https",
}
VISITOR, VERCEL, RENDER_LB = "220.158.168.162", "65.2.144.101", "10.27.213.240"


def req(headers=None, host=RENDER_LB):
    return SimpleNamespace(headers=dict(headers or {}), client=SimpleNamespace(host=host))


@pytest.fixture
def settings(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "TRUSTED_PROXY_HOPS", 1)
    monkeypatch.setattr(s, "CLIENT_IP_HEADER", "")
    monkeypatch.setattr(s, "FRONTEND_FORWARDS_CLIENT_IP", False)
    return s


def configure_for_vercel_and_cloudflare(s):
    s.CLIENT_IP_HEADER = "cf-connecting-ip"
    s.FRONTEND_FORWARDS_CLIENT_IP = True


class TestTheProductionCapture:
    def test_the_original_defaults_identified_everyone_as_renders_internal_proxy(self, settings):
        assert client_address(req(PRODUCTION_HEADERS)).client == RENDER_LB      # the bug: one address for all visitors

    def test_configured_for_vercel_and_cloudflare_the_visitor_is_found(self, settings):
        configure_for_vercel_and_cloudflare(settings)
        address = client_address(req(PRODUCTION_HEADERS))
        assert address.client == VISITOR
        assert address.peer == VERCEL

    def test_two_visitors_through_the_same_frontend_get_different_addresses(self, settings):
        configure_for_vercel_and_cloudflare(settings)
        other = {**PRODUCTION_HEADERS, "forwarded": "for=1.0.0.1;host=x;proto=https",
                 "x-forwarded-for": "1.0.0.1,65.2.144.101, 172.71.198.72, 10.27.213.240"}
        assert client_address(req(PRODUCTION_HEADERS)).client != client_address(req(other)).client
        assert client_address(req(PRODUCTION_HEADERS)).peer == client_address(req(other)).peer

    def test_the_cloudflare_header_alone_gives_the_connecting_address_not_the_visitor(self, settings):
        settings.CLIENT_IP_HEADER = "cf-connecting-ip"
        address = client_address(req(PRODUCTION_HEADERS))
        assert address.client == address.peer == VERCEL                          # shared by everyone behind Vercel

    def test_the_forwarded_address_is_ignored_unless_the_frontend_is_trusted(self, settings):
        settings.CLIENT_IP_HEADER = "cf-connecting-ip"
        assert client_address(req(PRODUCTION_HEADERS)).client != VISITOR


class TestForwardedAddressValidation:
    @pytest.mark.parametrize("forwarded,xff", [
        ("for=10.0.0.5", "10.0.0.5, 65.2.144.101"),                      # private
        ("for=127.0.0.1", "127.0.0.1, 65.2.144.101"),                    # loopback
        ("for=not-an-ip", "not-an-ip, 65.2.144.101"),                    # garbage
        ("for=unknown", "unknown, 65.2.144.101"),
        ("", ""),                                                        # nothing forwarded
    ])
    def test_unusable_claims_fall_back_to_the_unforgeable_peer(self, settings, forwarded, xff):
        configure_for_vercel_and_cloudflare(settings)
        headers = {"cf-connecting-ip": VERCEL, "forwarded": forwarded, "x-forwarded-for": xff}
        assert client_address(req({k: v for k, v in headers.items() if v})).client == VERCEL

    @pytest.mark.parametrize("forwarded,expected", [
        ('for=8.8.8.8:4711;proto=https', "8.8.8.8"),             # IPv4 with a port
        ('for="[2606:4700:4700::1111]:4711"', "2606:4700:4700::1111"),                     # quoted IPv6 with a port
        ('for=2606:4700:4700::1111', "2606:4700:4700::1111"),                              # bare IPv6
        ('for=1.0.0.1, for=65.2.144.101', "1.0.0.1"),          # first element wins
        ('For=1.0.0.1;Host=x', "1.0.0.1"),                     # case-insensitive
    ])
    def test_forwarded_header_formats(self, settings, forwarded, expected):
        configure_for_vercel_and_cloudflare(settings)
        assert client_address(req({"cf-connecting-ip": VERCEL, "forwarded": forwarded})).client == expected

    def test_the_first_x_forwarded_for_entry_is_used_when_there_is_no_forwarded_header(self, settings):
        configure_for_vercel_and_cloudflare(settings)
        headers = {"cf-connecting-ip": VERCEL, "x-forwarded-for": f"{VISITOR}, {VERCEL}"}
        assert client_address(req(headers)).client == VISITOR


class TestWithoutAFrontendProxy:
    def test_x_forwarded_for_is_read_from_the_trusted_end(self, settings):
        assert client_address(req({"x-forwarded-for": "1.1.1.1, 9.9.9.9"})).client == "9.9.9.9"

    def test_hops_are_configurable(self, settings):
        settings.TRUSTED_PROXY_HOPS = 3
        headers = {"x-forwarded-for": "6.6.6.6, 8.8.4.4, 172.71.198.72, 10.27.213.240"}
        assert client_address(req(headers)).client == "8.8.4.4"

    def test_socket_address_when_no_proxy_headers(self, settings):
        assert client_address(req({}, host="192.0.2.10")).client == "192.0.2.10"


class TestNetworkCheckGuidance:
    def test_default_settings_explain_the_problem_and_the_fix(self, settings):
        info = describe(req(PRODUCTION_HEADERS))
        assert info["detected_client_ip"] == RENDER_LB
        text = " ".join(info["notes"])
        assert "private" in text and "CLIENT_IP_HEADER" in text
        assert VISITOR in text and "FRONTEND_FORWARDS_CLIENT_IP" in text
        assert "cf-connecting-ip" in text

    def test_a_correct_configuration_is_reported_as_consistent(self, settings):
        configure_for_vercel_and_cloudflare(settings)
        info = describe(req(PRODUCTION_HEADERS))
        assert info["detected_client_ip"] == VISITOR and info["peer_ip"] == VERCEL
        assert info["forwarded_client_candidate"] == VISITOR
        assert len(info["notes"]) == 1 and "consistent" in info["notes"][0]
        assert info["headers"]["cf-connecting-ip"] == VERCEL
