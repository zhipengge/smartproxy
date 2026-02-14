"""
SmartProxy Package
"""

__version__ = "1.0.0"
__author__ = "Pumpkin"

from smartproxy.core import SmartProxyCore, ProxyRule, TrafficStats
from smartproxy.config import Config

__all__ = ["SmartProxyCore", "ProxyRule", "TrafficStats", "Config"]
