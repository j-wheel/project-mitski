import re

import discord

USER_MENTION = re.compile(r"<@!?\d+>")
ROLE_MENTION = re.compile(r"<@&\d+>")
CHANNEL_MENTION = re.compile(r"<#\d+>")
EVERYONE_MENTION = re.compile(r"@(everyone|here)\b")
CUSTOM_EMOJI = re.compile(r"<a?:(\w+):\d+>")
ANY_URL = re.compile(r"(?:https?://|www\.)\S+|\b(?:discord\.gg|discord\.com/invite)/\S+", re.I)
YT_URL = re.compile(
    r"(?:https?://)?(?:www\.|m\.|music\.)?(?:youtube\.com/(?:watch\?(?:\S*?&)?v=|shorts/|live/|embed/)|youtu\.be/)([\w-]{11})",
    re.I,
)
STICKER_TAG = re.compile(r"\[sticker:\s*([^\]\(]{1,40}?)\s*(?:\([^\]]*\))?\s*\]", re.I)
LOW_EFFORT = re.compile(
    r"^(?:lo+l+|lma+o+|lmfa+o+|ha(?:ha)+h?|he(?:he)+|xd+|ok(?:ay)?|kk?|ty(?:sm)?|thx|thanks?(?: u| you)?|np|gn|gm|"
    r"nice|bet|real|true|fr|same|yes|ya|yea|yeah|nah|<3|💀|😂|😭|🤣|❤️?|👍|🥰)[\s!.]*$",
    re.I,
)
NO_PINGS = discord.AllowedMentions.none()
NEVER = -1e12
ROBOTIC = re.compile(
    r"\b(i (cannot|can'?t) assist|"
    r"how (can|may) i (help|assist) you|i'?m here to help|is there anything else i can|"
    r"i don'?t have (personal )?(feelings|opinions|a body)|notes only you can see|my notes say)\b",
    re.I,
)
SERVILE = re.compile(
    r"\b(?:i will (?:remind|ping|tell|let (?:you|u|him|her|them) know|make sure|send|do (?:that|it|this)|check|"
    r"get back)|(?:here'?s|here is) (?:a|an|the|your|my) (?:quick |simple |easy |basic )?(?:recipe|list|guide|step|"
    r"breakdown|summary|rundown|overview)|step \d|you(?:'ll| will) need|certainly|happy to help|glad to help|"
    r"feel free to|hope (?:this|that) helps|let me know if (?:you|u) (?:need|have|want)|as (?:you )?requested|"
    r"consider it done|your request|i'?ve (?:set|scheduled|noted))\b|\b(?:ingredients?|instructions?|steps?|"
    r"method|directions):",
    re.I,
)
LIST_LINE = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+\S")
JUST_HI = re.compile(
    r"^\W*(?:@[\w.'-]{1,32}\W+)?(?:hi+|hey+|hello+|helo|yo+|sup|wsg|wassup|howdy|hiya|heya|hai|haii+|gm|good\s*morning|"
    r"morning|mornin|good\s*(?:evening|afternoon)|evening)\W*(?:@?[\w.'-]{1,32})?\W*$",
    re.I,
)
PING_TAG = re.compile(r"<@!?(\d+)>")
