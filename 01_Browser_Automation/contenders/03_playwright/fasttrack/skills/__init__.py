"""
Fast-Track Skills Module.
"""

from .youtube import YouTubeSkill
from .amazon import AmazonSkill
from .google import GoogleSkill
from .general import GeneralSkill

__all__ = ["YouTubeSkill", "AmazonSkill", "GoogleSkill", "GeneralSkill"]
