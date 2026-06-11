# Chameleon FABNetv4 Route Metrics
# Source: LoomAI validated Chameleon/FABRIC cross-testbed pattern
#
# Apply explicit route metrics to every Chameleon server that attaches to
# fabnetv4, even if the server has only one NIC. FABNet DHCP can install an IPv4
# default route; giving the FABNet interface a high metric prevents it from
# becoming the preferred public egress path when a management interface is also
# present.
#
# For the common public-SSH layout, use sharednet1 for management/floating-IP SSH
# and fabnetv4 for the FABNet dataplane. Without explicit DHCP route metrics,
# both interfaces can install equal-metric IPv4 default routes. SSH can enter
# through sharednet1 while replies leave through fabnetv4, causing asymmetric
# routing and SSH timeouts.
#
# Use this cloud-init/netplan userdata when launching Chameleon nodes with:
#   NIC 0: sharednet1, route metric 50
#   NIC 1: fabnetv4, route metric 500
#
# Common Ubuntu 22.04/24.04 Chameleon interface names:
#   sharednet1 -> eno1np0
#   fabnetv4   -> eno2np1
#
# For FABNet-only or single-NIC servers, set route-metric 500 on whichever
# interface is attached to fabnetv4. Verify interface names with `ip link` for
# new images or hardware. Preserve the FABNet route for 10.128.0.0/10 and verify
# it after boot with:
#   ip route | grep 10.128

from __future__ import annotations

import base64


def build_route_metrics_cloud_init(
    *,
    sharednet_iface: str | None = "eno1np0",
    fabnet_iface: str = "eno2np1",
    sharednet_metric: int = 50,
    fabnet_metric: int = 500,
) -> str:
    """Build cloud-init that sets DHCP route metrics for Chameleon FABNet.

    Pass sharednet_iface=None for a FABNet-only or single-NIC server, and set
    fabnet_iface to the actual OS interface attached to fabnetv4.
    """
    stanzas: list[str] = []
    if sharednet_iface:
        stanzas.append(
            f"""          {sharednet_iface}:
            dhcp4-overrides:
              route-metric: {sharednet_metric}"""
        )
    stanzas.append(
        f"""          {fabnet_iface}:
            dhcp4-overrides:
              route-metric: {fabnet_metric}"""
    )
    return """#cloud-config
write_files:
  - path: /etc/netplan/99-chameleon-route-metrics.yaml
    owner: root:root
    permissions: '0600'
    content: |
      network:
        version: 2
        ethernets:
{stanzas}
runcmd:
  - [ netplan, apply ]
""".format(stanzas="\n".join(stanzas))


CHAMELEON_FABNETV4_ROUTE_METRICS_CLOUD_INIT = build_route_metrics_cloud_init()


def chameleon_route_metric_user_data() -> str:
    """Return cloud-init for sharednet1 + fabnetv4 route metrics."""
    return CHAMELEON_FABNETV4_ROUTE_METRICS_CLOUD_INIT


def chameleon_fabnet_only_user_data(fabnet_iface: str = "eno1np0") -> str:
    """Return cloud-init for a FABNet-only or single-NIC Chameleon server."""
    return build_route_metrics_cloud_init(sharednet_iface=None, fabnet_iface=fabnet_iface)


def nova_user_data_base64(user_data: str = CHAMELEON_FABNETV4_ROUTE_METRICS_CLOUD_INIT) -> str:
    """Return the base64-encoded user_data value used by the Nova REST API."""
    return base64.b64encode(user_data.encode("utf-8")).decode("ascii")


def build_dual_nic_server_body(
    *,
    name: str,
    image_ref: str,
    flavor_ref: str,
    key_name: str,
    reservation_id: str,
    sharednet1_id: str,
    fabnetv4_id: str,
) -> dict:
    """Build a Nova server-create body for a dual-NIC Chameleon node.

    The first network is the management path for public floating-IP SSH. The
    second network is the FABNetv4 dataplane for FABRIC-Chameleon traffic.
    """
    return {
        "server": {
            "name": name,
            "imageRef": image_ref,
            "flavorRef": flavor_ref,
            "key_name": key_name,
            "networks": [
                {"uuid": sharednet1_id},
                {"uuid": fabnetv4_id},
            ],
            "scheduler_hints": {"reservation": reservation_id},
            "user_data": nova_user_data_base64(),
        }
    }


def build_fabnet_only_server_body(
    *,
    name: str,
    image_ref: str,
    flavor_ref: str,
    key_name: str,
    reservation_id: str,
    fabnetv4_id: str,
    fabnet_iface: str = "eno1np0",
) -> dict:
    """Build a Nova body for a server whose only attached network is fabnetv4."""
    return {
        "server": {
            "name": name,
            "imageRef": image_ref,
            "flavorRef": flavor_ref,
            "key_name": key_name,
            "networks": [{"uuid": fabnetv4_id}],
            "scheduler_hints": {"reservation": reservation_id},
            "user_data": nova_user_data_base64(chameleon_fabnet_only_user_data(fabnet_iface)),
        }
    }


VERIFY_AFTER_BOOT = [
    "ip link",
    "ip route show default",
    "ip route | grep 10.128",
    "ip route get 8.8.8.8",
]


OPERATIONAL_NOTE = (
    "FABNet-only Chameleon nodes may accept floating IPs at some sites, but for "
    "reliable public SSH plus FABNet dataplane connectivity, prefer "
    "sharednet1 + fabnetv4 with explicit route metrics."
)


if __name__ == "__main__":
    print(chameleon_route_metric_user_data())
