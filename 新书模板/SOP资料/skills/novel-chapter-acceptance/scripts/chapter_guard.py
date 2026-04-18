#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable
import xml.etree.ElementTree as ET


TITLE_RE = re.compile(r"^第([0-9一二三四五六七八九十百千零〇两]+)章\s+\S+")
RANGE_RE = re.compile(r"每章目标(?:字数)?[^0-9]{0,20}(\d+)\s*[—\-~至到]\s*(\d+)\s*字")
MIN_RE = re.compile(r"(?:每章最低(?:字数)?|最低(?:字数)?)[^0-9]{0,20}(?:不低于\s*)?(\d+)\s*字")
URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
HTML_RE = re.compile(r"<[^>]+>")
BAD_CHAR_RE = re.compile(r"�")
SPACE_RE = re.compile(r"\s+")
FILE_CHAPTER_RE = re.compile(r"(?<!\d)(\d{1,4})(?:[_-]|$)")
COUNT_REFERENCE_RE = re.compile(r"(这|那)([0-9零〇一二三四五六七八九十两]+)个字")
QUOTE_CONTENT_RE = re.compile(r"[“\"「『](.*?)[”\"」』]")
COUNT_NOUN_FOLLOW = r"(?=[，。！？；：“”\"」』、\s]|都|也|便|就|还|又|却|在|将|把|被|不|没|未|正|先|再|仍|已|才|并|忽|说|道|问|答|看|听|走|站|跪|退|进|抬|低)"
GENERAL_COUNT_NOUN_RE = re.compile(
    r"([0-9零〇一二三四五六七八九十百千两]+)"
    r"(个|名|位|人|封|件|把|柄|座|处|条|本|章|句|字|声|回|步|间|匹|张|碗|口|队|箱|页|骑)"
    r"([\u4e00-\u9fff]{0,4}?)"
    + COUNT_NOUN_FOLLOW
)
THIS_THAT_COUNT_NOUN_RE = re.compile(
    r"(这|那)"
    r"([0-9零〇一二三四五六七八九十百千两]+)"
    r"(个|名|位|人|封|件|把|柄|座|处|条|本|章|句|字|声|回|步|间|匹|张|碗|口|队|箱|页|骑)"
    r"([\u4e00-\u9fff]{0,4}?)"
    + COUNT_NOUN_FOLLOW
)
RELATIVE_DAY_RE = re.compile(r"([0-9零〇一二三四五六七八九十百千两]+)(?:日|天)后")
HALF_MONTH_RE = re.compile(r"半(?:个)?月后")
RELATIVE_MONTH_RE = re.compile(r"([0-9零〇一二三四五六七八九十百千两]+)个?月后")
NAME_TITLE_RE = re.compile(
    r"([\u4e00-\u9fff]{1,4})"
    r"(将军|大人|尚书|侍郎|统领|校尉|夫人|娘子|小姐|姑娘|少夫人|王妃|郡主|娘娘|陛下|皇上|圣上|天子|王爷|太子|世子|公子|殿下)"
)

TIME_LITERAL_MARKERS = [
    ("当日", 0, "当日"),
    ("当天", 0, "当天"),
    ("是日", 0, "是日"),
    ("当晚", 1, "当晚"),
    ("当夜", 1, "当夜"),
    ("入夜", 1, "入夜"),
    ("夜里", 1, "夜里"),
    ("夜深后", 1, "夜深后"),
    ("这一夜", 1, "这一夜"),
    ("次日", 2, "次日"),
    ("翌日", 2, "翌日"),
    ("第二日", 2, "第二日"),
    ("第二天", 2, "第二天"),
    ("次夜", 3, "次夜"),
    ("翌夜", 3, "翌夜"),
    ("第二夜", 3, "第二夜"),
]
FLASHBACK_CUES = (
    "想起",
    "从前",
    "那年",
    "那时候",
    "昔日",
    "昔年",
    "此前",
    "当初",
    "曾经",
    "记得",
    "回想",
    "旧时",
    "幼时",
    "少年时",
)
TITLE_CLUSTER_MAP = {
    "陛下": "ruler",
    "皇上": "ruler",
    "圣上": "ruler",
    "天子": "ruler",
    "王爷": "royal",
    "太子": "royal",
    "世子": "royal",
    "殿下": "royal",
    "将军": "official",
    "大人": "official",
    "尚书": "official",
    "侍郎": "official",
    "统领": "official",
    "校尉": "official",
    "公子": "gentry",
    "夫人": "domestic",
    "娘子": "domestic",
    "小姐": "domestic",
    "姑娘": "domestic",
    "少夫人": "domestic",
    "王妃": "domestic",
    "郡主": "domestic",
    "娘娘": "domestic",
}
INCOMPATIBLE_TITLE_CLUSTERS = {
    frozenset(("ruler", "royal")),
    frozenset(("ruler", "official")),
    frozenset(("ruler", "gentry")),
    frozenset(("ruler", "domestic")),
    frozenset(("royal", "official")),
    frozenset(("royal", "domestic")),
    frozenset(("official", "domestic")),
}
IDENTITY_NOUN_RE = re.compile(
    r"([\u4e00-\u9fff]{2,4})(女官|内侍|宫女|公子|姑娘|小姐|夫人|娘子|绣娘|医女|寡妇)"
)
IDENTITY_CLUSTER_MAP = {
    "女官": "female_attendant",
    "宫女": "female_attendant",
    "内侍": "male_attendant",
    "公子": "male_gentry",
    "姑娘": "female_gentry",
    "小姐": "female_gentry",
    "夫人": "female_married",
    "娘子": "female_married",
    "绣娘": "female_worker",
    "医女": "female_worker",
    "寡妇": "female_married",
}
INCOMPATIBLE_IDENTITY_CLUSTERS = {
    frozenset(("female_attendant", "male_attendant")),
    frozenset(("male_gentry", "female_gentry")),
    frozenset(("male_gentry", "female_married")),
    frozenset(("male_gentry", "female_worker")),
    frozenset(("male_attendant", "female_gentry")),
    frozenset(("male_attendant", "female_married")),
    frozenset(("male_attendant", "female_worker")),
}
BODY_PART_RE = (
    "左手|右手|左臂|右臂|左肩|右肩|左腿|右腿|左眼|右眼|左脸|右脸|左腕|右腕|左膝|右膝|左脚|右脚"
)
INJURY_STATE_RE = re.compile(
    rf"([\u4e00-\u9fff]{{2,4}})(?:的)?({BODY_PART_RE})([^，。！？；]{{0,8}})"
    rf"(受伤|有伤|带伤|伤着|缠着纱布|缠着布条|渗着血|渗血|裂了|裂开了|肿着|断了|折了|瘸着|抬不起来|使不上力|吊着)"
)
INJURY_RECOVERY_RE = re.compile(
    rf"([\u4e00-\u9fff]{{2,4}})(?:的)?({BODY_PART_RE})([^，。！？；]{{0,8}})"
    rf"(完好无损|完好的|没受伤|无伤|好好的|灵活自如|活动如常|抬得很稳|稳稳当当)"
)
HEALING_CUES = (
    "伤好了",
    "养好了",
    "痊愈",
    "结痂",
    "恢复如常",
    "慢慢养好",
    "养了几日",
    "过了几日",
    "隔了几日",
    "数日后",
    "半月后",
    "半个月后",
    "一月后",
    "一个月后",
)
STOCK_ASSERT_RE = re.compile(
    r"(只剩|还剩|剩下|余下|只余|还有|现有|手里还有|手里只剩|账上还有|账上只剩|库里还有|库里只剩|仓里还有|仓里只剩|家里还有|家里只剩)"
    r"([0-9零〇一二三四五六七八九十百千两]+)"
    r"(两银子|两银|银子|文钱|吊钱|铜钱|袋粮食|袋粮|石粮|斗米|斤米|袋米|斤粮|粮食|斤盐|包盐|袋盐|包药材|斤药材|匹布|袋种子|包种子)"
)
STOCK_RESOURCE_MAP = {
    "两银子": "silver",
    "两银": "silver",
    "银子": "silver",
    "文钱": "copper",
    "吊钱": "copper",
    "铜钱": "copper",
    "袋粮食": "grain",
    "袋粮": "grain",
    "石粮": "grain",
    "斗米": "grain",
    "斤米": "grain",
    "袋米": "grain",
    "斤粮": "grain",
    "粮食": "grain",
    "斤盐": "salt",
    "包盐": "salt",
    "袋盐": "salt",
    "包药材": "herb",
    "斤药材": "herb",
    "匹布": "cloth",
    "袋种子": "seed",
    "包种子": "seed",
}
STOCK_FLOW_CUES = (
    "买了",
    "卖了",
    "花了",
    "用了",
    "用掉",
    "分了",
    "换回",
    "收到",
    "得了",
    "赚了",
    "借来",
    "送来",
    "运来",
    "添了",
    "增了",
    "少了",
    "丢了",
    "被抢",
    "进账",
    "出账",
    "支出",
    "拿到",
    "领到",
    "收进",
    "收上来",
)
ONLY_PRESENT_ONE_RE = re.compile(r"只(?:剩|余|有)([\u4e00-\u9fff]{2,4})一人")
ONLY_PRESENT_TWO_RE = re.compile(r"只(?:剩|余|有)([\u4e00-\u9fff]{2,4})和([\u4e00-\u9fff]{2,4})")
EXIT_NAME_RE = re.compile(
    r"([\u4e00-\u9fff]{2,4})(?:退了出去|退下了|退下|转身便走|转身离开|快步离开|走了出去|出了门|出门去了|告退|离开了|退了下去)"
)
ENTRY_NAME_RE = re.compile(
    r"([\u4e00-\u9fff]{2,4})(?:进来|走进来|推门进来|快步进来|入内|回来|赶来|跟进来|迈进门|进了门|进门来|进了殿|进了屋|追了上来|走了过来)"
)
NAME_ACTION_RE = re.compile(
    r"([\u4e00-\u9fff]{2,4})(?:道|说|问|答|应|开口|笑了|皱眉|抬眼|看向|看着|转身|上前|走到|站在|坐在|跪下|低声|递来|伸手|点头|摇头|接话)"
)
STATIC_LOCATION_RE = re.compile(
    r"(?:在|仍在|还在|正站在|站在|立在|留在|身处|置身|坐在|跪在|候在|守在)"
    r"([\u4e00-\u9fff]{1,8}"
    r"(?:门前|门口|门外|门内|殿前|殿外|殿内|殿中|宫门|宫中|宫里|殿门|偏殿|廊下|廊外|"
    r"院里|院中|屋里|屋中|帐中|帐里|街上|长街|营门外|营中|校场|城头|城下|堡门前|"
    r"堡门外|桥边|亭中|堂中|府中|城门外|城门口))"
)
LEADING_LOCATION_RE = re.compile(
    r"^([\u4e00-\u9fff]{1,8}"
    r"(?:门前|门口|门外|门内|殿前|殿外|殿内|殿中|宫门|宫中|宫里|殿门|偏殿|廊下|廊外|"
    r"院里|院中|屋里|屋中|帐中|帐里|街上|长街|营门外|营中|校场|城头|城下|堡门前|"
    r"堡门外|桥边|亭中|堂中|府中|城门外|城门口))"
    r"(?=的|里|中|外)"
)
MOVEMENT_CUES = (
    "走到",
    "走出",
    "走进",
    "踏进",
    "踏出",
    "回到",
    "转到",
    "转进",
    "转出",
    "来到",
    "赶到",
    "到了",
    "到",
    "出了",
    "进了",
    "进去",
    "出来",
    "回去",
    "回宫",
    "回营",
    "离开",
    "穿过",
    "越过",
    "出了宫门",
    "进了偏殿",
)
OBJECT_TERMS = [
    "刀",
    "刀柄",
    "剑",
    "枪",
    "名册",
    "婚旨",
    "妆匣",
    "玉如意",
    "箭囊",
    "披风",
    "缰绳",
    "信",
    "账册",
    "药碗",
    "托盘",
]
OBJECT_CANONICAL_MAP = {
    "刀": "刀",
    "刀柄": "刀",
    "剑": "剑",
    "枪": "枪",
    "名册": "名册",
    "婚旨": "婚旨",
    "妆匣": "妆匣",
    "玉如意": "玉如意",
    "箭囊": "箭囊",
    "披风": "披风",
    "缰绳": "缰绳",
    "信": "信",
    "账册": "账册",
    "药碗": "药碗",
    "托盘": "托盘",
}
OBJECT_HELD_CUES = [
    "握着",
    "握住",
    "按着",
    "按住",
    "扶着",
    "提着",
    "拿着",
    "抱着",
    "佩着",
    "挂着",
    "攥着",
    "捏着",
    "背着",
    "端着",
    "握在手里",
    "按在掌心",
    "挂在腰间",
    "抱在怀里",
    "背在身后",
    "佩在腰间",
    "仍在腰间",
    "还在手中",
    "还在腰间",
]
OBJECT_AWAY_CUES = [
    "解下",
    "摘下",
    "放下",
    "搁下",
    "收起",
    "收入",
    "塞回",
    "放回",
    "交给",
    "递给",
    "放进",
    "被放下",
    "被搁下",
    "被收起",
    "被放回",
    "被交给",
    "离了手",
]
OBJECT_REACQUIRE_CUES = (
    "重新",
    "再",
    "又",
    "拿回",
    "取回",
    "拾起",
    "捡起",
    "接过",
    "拿起",
    "取过",
)
QUOTE_ONLY_RE = re.compile(r'^[“"「『][^“”"「」『』]{2,120}[”"」』][。！？!?…；;，,、]*$')
SPEECH_VERB_PATTERN = (
    r"(?:低声道|轻声道|沉声道|冷声道|哑声道|淡淡道|冷笑道|缓声道|说道|问道|答道|应道|回道|"
    r"喝道|斥道|骂道|笑道|回话|开口|说|问|答|应|道)"
)
NAME_SPEECH_BEFORE_RE = re.compile(
    rf"([\u4e00-\u9fff]{{2,4}}?){SPEECH_VERB_PATTERN}[^“”\"「」『』]{{0,6}}[“\"「『]([^”\"」』]{{2,120}})[”\"」』]"
)
NAME_SPEECH_AFTER_RE = re.compile(
    rf"[“\"「『]([^”\"」』]{{2,120}})[”\"」』][^“”\"「」『』\n]{{0,6}}([\u4e00-\u9fff]{{2,4}}?){SPEECH_VERB_PATTERN}"
)
NAME_SPEECH_TAG_RE = re.compile(rf"([\u4e00-\u9fff]{{2,4}}?){SPEECH_VERB_PATTERN}")
FORMAL_STRONG_MARKERS = (
    "臣",
    "末将",
    "卑职",
    "属下",
    "下官",
    "妾身",
    "民女",
)
FORMAL_WEAK_MARKERS = (
    "殿下",
    "陛下",
    "圣上",
    "不敢",
    "不曾",
    "未曾",
    "不可",
    "岂可",
    "请恕",
)
COLLOQUIAL_MARKERS = (
    "老娘",
    "姑奶奶",
    "滚蛋",
    "闭嘴",
    "烦死",
    "得了吧",
    "咋",
    "可不",
    "少来",
    "别磨叽",
    "晦气",
    "见鬼",
    "胡扯",
    "废话",
    "真行",
)
VOICE_SOFTEN_CUES = (
    "笑",
    "怒",
    "骂",
    "喝",
    "讥",
    "打趣",
    "故意",
    "学着",
    "模仿",
    "醉了",
    "哽咽",
    "哭",
    "气急",
)
TASK_TOPIC_KEYWORDS = {
    "粮食": ("粮", "粮食", "口粮", "米", "米粮", "军粮"),
    "银钱": ("银子", "现银", "铜钱", "盘缠", "钱袋", "银钱"),
    "住处": ("住处", "落脚处", "屋子", "房子", "院子", "安身处"),
    "药材": ("药材", "汤药", "药", "药包"),
    "水源": ("井", "水源", "水缸", "吃水", "井水"),
    "田地": ("田", "田地", "荒地", "地"),
    "铺子": ("铺子", "店面", "作坊", "生意"),
    "身份文书": ("名册", "户籍", "路引", "文书", "身份"),
    "军械": ("军械", "兵器", "刀枪", "弓箭"),
}
TASK_RESOLVED_CUES = (
    "不缺",
    "够了",
    "够撑",
    "有着落了",
    "有着落",
    "办妥",
    "定下",
    "盘下",
    "租下",
    "买下",
    "开起来",
    "立住",
    "备齐",
    "凑齐",
    "补齐",
    "通了",
    "成了",
    "稳了",
    "有了",
    "不再缺",
)
TASK_PROBLEM_CUES = (
    "最难的还是",
    "眼下最难的是",
    "眼下最难的还是",
    "头一桩难事",
    "头一件难事",
    "首要难题",
    "最大难题",
    "最缺的就是",
    "最缺的是",
    "发愁的还是",
    "犯难的还是",
    "一点也没有",
    "半点都没有",
    "还没着落",
    "没有着落",
    "紧缺",
    "短缺",
    "不够用",
    "撑不住",
)
TASK_SETBACK_CUES = (
    "被抢",
    "被烧",
    "被偷",
    "断供",
    "耗尽",
    "见底",
    "没了",
    "毁了",
    "塌了",
    "出事",
    "生变",
    "涨价",
)
NON_NAME_PREFIXES = (
    "不是",
    "只是",
    "还是",
    "便是",
    "她知",
    "他知",
    "这里",
    "那里",
    "哪里",
    "如今",
    "自然",
    "眼下",
    "回头",
    "若是",
    "若非",
)
NON_NAME_TOKENS = {
    "忽然",
    "忽地",
    "忽而",
    "随后",
    "旋即",
    "立刻",
    "顿时",
    "一时",
    "这时",
    "此时",
    "当下",
    "低头",
    "抬头",
}
NON_NAME_PARTS = (
    "这几",
    "那几",
    "几道",
    "几条",
    "几个",
    "几名",
    "几位",
    "几步",
    "几间",
    "几口",
)
SILENCE_STATE_RE = re.compile(
    r"([\u4e00-\u9fff]{2,4})(?:没有说话|没说话|未答|没有作答|没作答|并不作答|没有应声|没应声|"
    r"没有开口|没开口|没有接话|没接话|只是沉默|沉默不语|一言不发)"
)
DIALOGUE_RESUME_CUES = (
    "片刻后",
    "过了片刻",
    "隔了片刻",
    "过了一会",
    "过了一阵",
    "良久",
    "半晌",
    "静了静",
    "沉默了一会",
    "终于",
    "到底",
    "末了",
)
POV_HOLDER_STOPWORDS = {
    "众人",
    "众将",
    "众将士",
    "礼部",
    "兵部",
    "宫中",
    "宫里",
    "宫人",
    "内侍",
    "女官",
    "宫女",
    "掌柜",
    "伙计",
    "将军",
    "公子",
    "姑娘",
    "夫人",
    "娘子",
    "陛下",
    "皇上",
    "圣上",
    "天子",
}
POV_INNER_STATE_RE = re.compile(
    r"([\u4e00-\u9fff]{2,4})(?:心里|心中|心下一|暗自|暗暗|想着|想道|知道|明白|清楚|意识到|"
    r"后悔|庆幸|害怕|发慌|松了口气|打定主意|盘算着|猛地想起|忽然想起)"
)
POV_SHIFT_CUES = (
    "另一边",
    "与此同时",
    "而此刻",
    "另一头",
    "另一处",
    "另一侧",
    "再看",
    "再说",
    "回到",
    "转到",
    "视线转到",
    "宫墙那头",
)
RELATION_WARM_PATTERNS = (
    re.compile(r"([\u4e00-\u9fff]{2,4})终于肯信([\u4e00-\u9fff]{2,4})"),
    re.compile(r"([\u4e00-\u9fff]{2,4})总算信了([\u4e00-\u9fff]{2,4})"),
    re.compile(r"([\u4e00-\u9fff]{2,4})不再防着([\u4e00-\u9fff]{2,4})"),
    re.compile(r"([\u4e00-\u9fff]{2,4})愿意信([\u4e00-\u9fff]{2,4})"),
    re.compile(r"([\u4e00-\u9fff]{2,4})肯把后背交给([\u4e00-\u9fff]{2,4})"),
    re.compile(r"([\u4e00-\u9fff]{2,4})把后背交给了([\u4e00-\u9fff]{2,4})"),
    re.compile(r"([\u4e00-\u9fff]{2,4})对([\u4e00-\u9fff]{2,4})的声音放软了"),
    re.compile(r"([\u4e00-\u9fff]{2,4})朝([\u4e00-\u9fff]{2,4})笑了"),
)
RELATION_ROLLBACK_PATTERNS = (
    re.compile(r"([\u4e00-\u9fff]{2,4})(?:还是|仍|依旧|仍旧|依然).{0,4}(?:不信|防着|避着|躲着)([\u4e00-\u9fff]{2,4})"),
    re.compile(r"([\u4e00-\u9fff]{2,4})对([\u4e00-\u9fff]{2,4})(?:还是|仍|依旧|依然).{0,4}(?:客客气气|生分|疏离)"),
    re.compile(r"([\u4e00-\u9fff]{2,4})(?:还是|仍|依旧|依然).{0,6}不肯靠近([\u4e00-\u9fff]{2,4})"),
    re.compile(r"([\u4e00-\u9fff]{2,4})又拉开了与([\u4e00-\u9fff]{2,4})的距离"),
)
RELATION_SETBACK_CUES = (
    "误会",
    "翻脸",
    "争执",
    "争吵",
    "背叛",
    "算计",
    "试探",
    "受伤",
    "中刀",
    "被抓",
    "被罚",
    "出事",
    "失手",
    "消息传来",
)
NAME_TRAILING_PARTICLES = ("也", "都", "又", "便", "就", "还", "才", "却", "只")
STANCE_TARGET_STOPWORDS = {
    "这边",
    "那边",
    "一边",
    "这儿",
    "那儿",
    "这里",
    "那里",
    "原处",
}
STANCE_TARGET_SUFFIXES = (
    "门前",
    "门口",
    "门外",
    "门内",
    "殿前",
    "殿外",
    "殿内",
    "殿中",
    "廊下",
    "廊外",
    "院里",
    "院中",
    "屋里",
    "屋中",
    "帐中",
    "帐里",
    "街上",
    "长街",
    "校场",
    "城头",
    "城下",
    "桥边",
    "亭中",
    "堂中",
    "府中",
    "角",
    "边",
    "下",
    "上",
    "里",
    "外",
    "中",
    "处",
)
EVENT_BRIDGE_CUES = (
    "片刻后",
    "过了片刻",
    "过了一会",
    "随后",
    "很快",
    "不多时",
    "终于",
    "等到",
    "待到",
    "直到",
    "半晌后",
    "过了一阵",
)
EVENT_GATE_PENDING_PATTERNS = (
    ("open_gate", re.compile(r"((?:城门|殿门|堡门|宫门|门))(?:还没开|尚未开启|尚未开|未开|没有打开|没打开)")),
    ("approval", re.compile(r"((?:陛下|她|他|朝廷|上头))(?:还没点头|尚未点头|未曾应允|没有松口|没松口|还没下令|尚未下旨)")),
    ("arrival", re.compile(r"((?:[\u4e00-\u9fff]{2,4}|消息|婚书|信))(?:还没到|尚未到|未到|还没送到|尚未送到|没送到)")),
    ("enter_hall", re.compile(r"((?:[\u4e00-\u9fff]{2,4}|众人))(?:还没进殿|尚未入殿|未入殿|还未进宫|尚未进宫)")),
    ("depart", re.compile(r"((?:[\u4e00-\u9fff]{2,4}|车队|队伍))(?:还没动身|尚未动身|尚未启程|还未启程)")),
)
EVENT_GATE_RESOLVED_PATTERNS = (
    ("open_gate", re.compile(r"((?:城门|殿门|堡门|宫门|门))(?:开了|一开|洞开|已经开了)")),
    ("approval", re.compile(r"((?:陛下|她|他|朝廷|上头))(?:点头了|应允了|松口了|下令了|下旨了|准了)")),
    ("arrival", re.compile(r"((?:[\u4e00-\u9fff]{2,4}|消息|婚书|信))(?:到了|赶到了|送到了|送来了|已经到了)")),
    ("enter_hall", re.compile(r"((?:[\u4e00-\u9fff]{2,4}|众人))(?:进了殿|入了殿|进宫了|入宫了)")),
    ("depart", re.compile(r"((?:[\u4e00-\u9fff]{2,4}|车队|队伍))(?:动身了|启程了|出发了|已经上路)")),
)
WORLD_CONSTANT_ASSERT_RE = re.compile(
    r"([\u4e00-\u9fff]{2,8}?)(?:一共|共有|总共|统共|下辖|统辖|有)"
    r"([0-9零〇一二三四五六七八九十百千两]+)"
    r"(州|郡|县|城|营|卫|门|司|部|坊|堡|寨|路|军|人|骑|船)"
)
WORLD_CONSTANT_CHANGE_CUES = (
    "扩编",
    "裁撤",
    "折损",
    "补入",
    "补进",
    "添了",
    "增至",
    "减至",
    "并入",
    "拆分",
    "调走",
    "调来",
    "新添",
    "补了",
    "少了",
)
OUTLINE_LINE_RE = re.compile(r"第([0-9一二三四五六七八九十百千零〇两]+)章[:：]?\s*(.*)")
PERMISSION_DENIAL_PATTERNS = (
    ("deploy_troops", re.compile(r"([\u4e00-\u9fff]{2,4})(?:无权|不得|不能|不可|不许|没资格|没有资格)(?:擅自)?调兵")),
    ("enter_palace", re.compile(r"([\u4e00-\u9fff]{2,4})(?:无权|不得|不能|不可|不许|没资格|没有资格)(?:擅自)?(?:入殿|进殿|入宫|进宫)")),
    ("view_records", re.compile(r"([\u4e00-\u9fff]{2,4})(?:无权|不得|不能|不可|不许|没资格|没有资格)(?:擅自)?(?:查阅卷宗|翻阅卷宗|查卷宗|阅档|查名册|看名册|翻名册)")),
    ("use_seal", re.compile(r"([\u4e00-\u9fff]{2,4})(?:无权|不得|不能|不可|不许|没资格|没有资格)(?:擅自)?(?:用印|盖印|开印|调档|发令|拿人|抓人)")),
)
PERMISSION_ACTION_PATTERNS = (
    ("deploy_troops", re.compile(r"([\u4e00-\u9fff]{2,4})(?:调兵|调来|调动|领来).{0,6}(?:兵|亲兵|甲士|骑兵|人马)?")),
    ("enter_palace", re.compile(r"([\u4e00-\u9fff]{2,4})(?:入殿|进殿|入宫|进宫|踏进殿内|踏进宫门)")),
    ("view_records", re.compile(r"([\u4e00-\u9fff]{2,4})(?:查阅卷宗|翻阅卷宗|查卷宗|阅档|查名册|看名册|翻名册)")),
    ("use_seal", re.compile(r"([\u4e00-\u9fff]{2,4})(?:用印|盖印|开印|调档|发令|拿人|抓人)")),
)
PERMISSION_GRANT_CUES = (
    "奉旨",
    "奉命",
    "奉诏",
    "得令",
    "得宣",
    "得了旨意",
    "传召",
    "宣入",
    "获准",
    "准其",
    "松口了",
    "拿着手令",
    "持令牌",
    "有印信",
    "有批文",
    "有腰牌",
    "陛下准了",
)
FORESHADOW_CANONICAL_PATTERNS = (
    (re.compile(r"封?信"), "信"),
    (re.compile(r"名册"), "名册"),
    (re.compile(r"婚书"), "婚书"),
    (re.compile(r"旧案|案子|案"), "旧案"),
    (re.compile(r"线索"), "线索"),
    (re.compile(r"疑点"), "疑点"),
    (re.compile(r"名字"), "名字"),
    (re.compile(r"身份"), "身份"),
    (re.compile(r"来路"), "来路"),
    (re.compile(r"真相"), "真相"),
    (re.compile(r"账"), "账"),
    (re.compile(r"婚事"), "婚事"),
)
FORESHADOW_PLANT_PATTERNS = (
    re.compile(r"((?:那|这|此)?(?:封?信|名册|婚书|旧案|线索|疑点|名字|身份|来路|真相|账|婚事))(?:先|暂且)?(?:记下|按下|压下|搁下|留待日后|留到日后)"),
    re.compile(r"((?:信|名册|婚书|旧案|线索|疑点|名字|身份|来路|真相|账|婚事))(?:还得|总要|迟早|改日|日后|回头).{0,6}(?:查清|问清|弄明白|再查|再问|再算|翻出来)"),
)
FORESHADOW_REVISIT_CUES = (
    "查",
    "问",
    "翻",
    "提起",
    "说起",
    "追",
    "对质",
    "交代",
    "揭开",
    "审",
    "算",
    "找到",
    "翻出",
    "查到",
    "问到",
)
GOAL_PENDING_PATTERNS = (
    re.compile(r"(?:当务之急是|眼下最要紧的是|眼下最急的是|眼下先得|接下来先得|如今先得|如今要紧的是|最先要做的是)([\u4e00-\u9fff]{2,12})"),
    re.compile(r"([\u4e00-\u9fff]{2,12})(?:才是眼下最要紧的事|才是当务之急)"),
)
GOAL_PROGRESS_CUES = (
    "办成",
    "办妥",
    "成了",
    "定下",
    "谈下",
    "拿到",
    "保住",
    "留下",
    "稳住",
    "立住",
    "解决",
    "说服",
    "查清",
    "有着落",
)
CHAR_RESOURCE_LOW_RE = re.compile(
    r"([\u4e00-\u9fff]{2,4})(?:手里|身上|怀里|包袱里|袖中)?(?:只剩|仅剩|还剩)"
    r"([0-9零〇一二三四五六七八九十百千两]+)"
    r"(两银子|两银|银子|文钱|铜钱|包药|包药材|袋粮|块饼|张饼|块干粮|壶水|袋米|斤米|袋盐|包盐)"
)
CHAR_RESOURCE_LAST_RE = re.compile(
    r"([\u4e00-\u9fff]{2,4})(?:手里|身上|怀里|包袱里)?(?:只剩最后|最后只剩)"
    r"(一)"
    r"(两银子|两银|银子|文钱|铜钱|包药|包药材|袋粮|块饼|张饼|块干粮|壶水|袋米|斤米|袋盐|包盐)"
)
CHAR_RESOURCE_SPEND_RE = re.compile(
    r"([\u4e00-\u9fff]{2,4})(?:掏出|拿出|递出|塞给|付了|给了|用了|分了|喝掉了|吃掉了|又给出|又递出)"
    r"([0-9零〇一二三四五六七八九十百千两]+)?"
    r"(两银子|两银|银子|文钱|铜钱|包药|包药材|袋粮|块饼|张饼|块干粮|壶水|袋米|斤米|袋盐|包盐)"
)
CHAR_RESOURCE_REPLENISH_CUES = (
    "买了",
    "换来",
    "得了",
    "收到",
    "借来",
    "送来",
    "添了",
    "补了",
    "拿到",
    "领到",
    "发下",
)
PROMISE_DEADLINE_CUES = (
    "明日",
    "明天",
    "今夜",
    "今晚",
    "天亮前",
    "三日内",
    "五日内",
    "七日内",
    "回京后",
    "月底前",
    "今夜前",
)
PROMISE_COMMIT_CUES = (
    "答应",
    "应下",
    "许诺",
    "承诺",
    "保证",
    "会给",
    "一定给",
    "一定把",
    "必定把",
    "必定给",
)
PROMISE_TOPIC_PATTERNS = (
    (re.compile(r"答复|回话|回信"), "答复"),
    (re.compile(r"交代"), "交代"),
    (re.compile(r"名册"), "名册"),
    (re.compile(r"婚书"), "婚书"),
    (re.compile(r"信"), "信"),
    (re.compile(r"药|药材|药包"), "药"),
    (re.compile(r"旧案|案子|案"), "旧案"),
    (re.compile(r"人带回来|把人带来|带她回来|带他回来"), "带人回来"),
)
PROMISE_FULFILL_CUES = (
    "给了答复",
    "有了答复",
    "回了话",
    "回了信",
    "给了交代",
    "交出来了",
    "送来了",
    "带回来了",
    "查清了",
    "办妥了",
    "兑现了",
)
PRIORITY_GOAL_PATTERNS = (
    re.compile(r"(?:别的都往后放|别的都先放下)[，,、 ]{0,2}先([\u4e00-\u9fff]{2,12})"),
    re.compile(r"(?:别的都往后放|别的都先放下|头一件事就是|先把|先得|先要)([\u4e00-\u9fff]{2,12})"),
    re.compile(r"(?:无论如何|怎么都得)先([\u4e00-\u9fff]{2,12})"),
)
PRIORITY_RESET_CUES = (
    "变故",
    "突发",
    "不得不先",
    "先缓一缓",
    "暂且放下",
    "另有旨意",
    "新的命令",
    "忽然",
    "出了岔子",
)
STANCE_SUPPORT_PATTERNS = (
    re.compile(r"([\u4e00-\u9fff]{2,4})(?:站到|站到了|倒向|投向)([\u4e00-\u9fff]{2,4})(?:这边|一边)?"),
    re.compile(r"([\u4e00-\u9fff]{2,4})站在([\u4e00-\u9fff]{2,4})(?:这边|一边)"),
    re.compile(r"([\u4e00-\u9fff]{2,4})(?:替|替着)([\u4e00-\u9fff]{2,4})说话"),
    re.compile(r"([\u4e00-\u9fff]{2,4})(?:帮着|护着|护住)([\u4e00-\u9fff]{2,4})"),
)
STANCE_OPPOSE_PATTERNS = (
    re.compile(r"([\u4e00-\u9fff]{2,4})(?:防着|针对|要动|要拿)([\u4e00-\u9fff]{2,4})"),
    re.compile(r"([\u4e00-\u9fff]{2,4})与([\u4e00-\u9fff]{2,4})(?:翻了脸|为敌)"),
)
STANCE_SWITCH_CUES = (
    "变卦",
    "倒戈",
    "做戏",
    "假意",
    "试探",
    "将计就计",
    "被迫",
    "逼不得已",
    "改了主意",
    "真相",
    "误会",
    "翻脸",
)
REVEAL_DENSITY_CUES = (
    "原来",
    "其实",
    "竟是",
    "竟然是",
    "这才知道",
    "这才明白",
    "真相是",
    "说破",
    "揭开",
    "揭穿",
    "认出",
    "身份是",
)
HOOK_CUES = (
    "？",
    "?",
    "却",
    "偏偏",
    "然而",
    "只是",
    "忽然",
    "未料",
    "没想到",
    "门外",
    "脚步声",
    "传旨",
    "敲门",
    "下一步",
    "明日",
    "今夜",
    "天亮",
    "还不知道",
    "只等",
)
FLAT_END_CUES = (
    "众人各自散去",
    "众人散去",
    "谁也没有再说话",
    "没有再说什么",
    "不再多想",
    "夜色渐深",
    "天色已晚",
    "风声渐紧",
    "风从廊下穿过",
    "便这样",
    "就此作罢",
    "一切又静了下来",
    "谁也没有开口",
)
EMOTION_SHOCK_PATTERNS = (
    re.compile(r"([\u4e00-\u9fff]{2,8})(?:死了|被杀了|中箭了|中刀了|被抓了|被拿下了|下狱了|被退婚了|被抄家了|要被流放了)"),
    re.compile(r"(圣旨已下|婚事已定|营被裁了|人没救回来|消息传来)"),
)
EMOTION_REACTION_CUES = (
    "一怔",
    "愣住",
    "心里一沉",
    "心口发紧",
    "指尖发冷",
    "脸色变了",
    "失声",
    "倒吸",
    "沉默了",
    "没说话",
    "没有说话",
    "问道",
    "追问",
    "皱眉",
    "发懵",
    "怔了一下",
    "呼吸一滞",
)
DECISION_PATTERNS = (
    re.compile(r"([\u4e00-\u9fff]{2,4})(?:当即|立刻|终于|还是)?(?:决定|打定主意|下定决心)([\u4e00-\u9fff]{2,12})"),
    re.compile(r"([\u4e00-\u9fff]{2,4})(?:咬牙|狠下心)(?:要|去|先去|先把)([\u4e00-\u9fff]{2,12})"),
)
DECISION_COST_CUES = (
    "代价",
    "风险",
    "一旦",
    "若是",
    "意味着",
    "就得",
    "就要",
    "只能放下",
    "只能丢下",
    "顾不上",
    "得罪",
    "赌上",
    "赔上",
    "舍掉",
    "换来",
    "会让",
)
FOCUS_TERM_STOPWORDS = {
    "裴照雪",
    "她",
    "他",
    "她们",
    "他们",
    "众人",
    "这一章",
    "这一场",
    "这件事",
    "那件事",
    "安排",
    "提醒",
    "真正",
    "终于",
    "一次",
    "一种",
    "一场",
    "体面里",
}
FOCUS_TERM_EDGE_CHARS = set("的一了是把被就还更像她他它们于从到向给让先再又仍并却但而里上中前后")
FOCUS_TERM_ANCHOR_TAILS = set("门殿营堡城墙案册令旨信路粮盐甲刀账药印井田约名水哨坊市场堡图规队门下")

CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
CHINESE_UNITS = {
    "十": 10,
    "百": 100,
    "千": 1000,
}


@dataclass
class RuleConfig:
    target_min: int = 3200
    target_max: int = 3800
    absolute_min: int = 3200


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="章节硬规则与连续性校验脚本")
    parser.add_argument("--chapter", required=True, help="当前章节文件，支持 .docx/.md/.txt")
    parser.add_argument("--rules", action="append", default=[], help="规则文件，可重复传入")
    parser.add_argument("--outline", help="总目录或大纲文件")
    parser.add_argument("--previous-dir", help="上一章节目录，脚本会自动筛选当前章之前的文件")
    parser.add_argument("--previous", action="append", default=[], help="手动指定要比较的前文章节，可重复传入")
    parser.add_argument("--format", choices=["text", "json"], default="text", help="输出格式")
    parser.add_argument("--near-threshold", type=float, default=0.9, help="近重复判定阈值")
    parser.add_argument("--recent-window", type=int, default=6, help="上一章尾段与本章开头重叠检查段数")
    return parser.parse_args()


def read_text(path: Path) -> tuple[list[str], str]:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        paragraphs = read_docx_paragraphs(path)
    else:
        text = path.read_text(encoding="utf-8", errors="ignore").replace("\r\n", "\n")
        paragraphs = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            line = re.sub(r"^[#>*\-]+\s*", "", line)
            if line:
                paragraphs.append(line)
    raw = "\n".join(paragraphs)
    return paragraphs, raw


def read_docx_paragraphs(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as zf:
        data = zf.read("word/document.xml")
    root = ET.fromstring(data)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []
    for p in root.findall(".//w:body//w:p", ns):
        texts = []
        for node in p.findall(".//w:t", ns):
            texts.append(node.text or "")
        text = "".join(texts).replace("\xa0", " ").strip()
        if text:
            paragraphs.append(text)
    return paragraphs


def normalize(text: str) -> str:
    return SPACE_RE.sub("", text)


def count_body_chars(paragraphs: list[str]) -> int:
    return len(normalize("".join(paragraphs)))


def count_visible_units(text: str) -> int:
    count = 0
    for ch in text:
        if ch.isspace():
            continue
        category = unicodedata.category(ch)
        if category.startswith(("L", "N")):
            count += 1
    return count


def canonical_count_label(unit: str, noun: str) -> str:
    noun = noun.strip()
    if noun:
        return f"{unit}{noun}"
    return unit


def chinese_to_int(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    total = 0
    current = 0
    seen = False
    for ch in token:
        if ch in CHINESE_DIGITS:
            current = CHINESE_DIGITS[ch]
            seen = True
            continue
        unit = CHINESE_UNITS.get(ch)
        if unit is None:
            return None
        seen = True
        if current == 0:
            current = 1
        total += current * unit
        current = 0
    if not seen:
        return None
    return total + current


def int_to_chinese(num: int) -> str:
    if num <= 0:
        return str(num)
    digits = "零一二三四五六七八九"
    units = ["", "十", "百", "千"]
    parts = []
    zero_pending = False
    chars = list(str(num))
    length = len(chars)
    for idx, ch in enumerate(chars):
        digit = int(ch)
        pos = length - idx - 1
        if digit == 0:
            zero_pending = bool(parts)
            continue
        if zero_pending:
            parts.append("零")
            zero_pending = False
        if not (digit == 1 and pos == 1 and not parts):
            parts.append(digits[digit])
        parts.append(units[pos])
    return "".join(parts)


def detect_chapter_number(title: str, path: Path) -> int | None:
    match = TITLE_RE.match(title)
    if match:
        return chinese_to_int(match.group(1))
    file_match = FILE_CHAPTER_RE.search(path.stem)
    if file_match:
        return int(file_match.group(1))
    return None


def parse_rules(rule_paths: Iterable[Path]) -> RuleConfig:
    config = RuleConfig()
    range_found = False
    min_found = False
    for path in rule_paths:
        if not path.exists():
            continue
        paragraphs, _ = read_text(path)
        text = "\n".join(paragraphs)
        for match in RANGE_RE.finditer(text):
            range_found = True
            config.target_min = int(match.group(1))
            config.target_max = int(match.group(2))
        for match in MIN_RE.finditer(text):
            min_found = True
            config.absolute_min = int(match.group(1))
    if range_found and not min_found:
        config.absolute_min = config.target_min
    return config


def find_exact_duplicates(paragraphs: list[str], min_len: int = 25) -> list[dict[str, object]]:
    seen: dict[str, list[int]] = defaultdict(list)
    samples: dict[str, str] = {}
    for idx, para in enumerate(paragraphs, start=1):
        key = normalize(para)
        if len(key) < min_len:
            continue
        seen[key].append(idx)
        samples[key] = para
    duplicates = []
    for key, indexes in seen.items():
        if len(indexes) > 1:
            duplicates.append(
                {
                    "indexes": indexes,
                    "sample": samples[key],
                }
            )
    return duplicates


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def find_near_duplicates(
    paragraphs: list[str], threshold: float, min_len: int = 80, limit: int = 6
) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    for idx, para in enumerate(paragraphs):
        if len(normalize(para)) < min_len:
            continue
        for jdx in range(idx + 1, len(paragraphs)):
            other = paragraphs[jdx]
            if len(normalize(other)) < min_len:
                continue
            ratio = similarity(para, other)
            if ratio >= threshold:
                issues.append(
                    {
                        "left_index": idx + 1,
                        "right_index": jdx + 1,
                        "ratio": round(ratio, 3),
                        "left_sample": para,
                        "right_sample": other,
                    }
                )
                if len(issues) >= limit:
                    return issues
    return issues


def find_count_reference_mismatches(paragraphs: list[str], lookback: int = 3) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    for idx, para in enumerate(paragraphs):
        for match in COUNT_REFERENCE_RE.finditer(para):
            expected = chinese_to_int(match.group(2))
            if expected is None:
                continue

            quoted = None
            quote_index = None
            for back in range(idx, max(-1, idx - lookback), -1):
                source_para = paragraphs[back]
                source_text = source_para if back != idx else source_para[: match.start()]
                candidates = QUOTE_CONTENT_RE.findall(source_text)
                if candidates:
                    quoted = candidates[-1]
                    quote_index = back + 1
                    break

            if not quoted:
                continue

            actual = count_visible_units(quoted)
            if actual != expected:
                issues.append(
                    {
                        "index": idx + 1,
                        "quote_index": quote_index,
                        "reference": match.group(0),
                        "quoted_text": quoted,
                        "expected": expected,
                        "actual": actual,
                        "paragraph": para,
                    }
                )
    return issues


def find_quantity_reference_mismatches(paragraphs: list[str], lookback: int = 3) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    for idx, para in enumerate(paragraphs):
        for match in THIS_THAT_COUNT_NOUN_RE.finditer(para):
            current_count = chinese_to_int(match.group(2))
            unit = match.group(3)
            noun = match.group(4)
            if current_count is None or current_count < 2:
                continue
            if unit == "字":
                continue
            label = canonical_count_label(unit, noun)

            nearest: dict[str, object] | None = None
            for back in range(idx, max(-1, idx - lookback - 1), -1):
                source = paragraphs[back] if back != idx else para[: match.start()]
                for prev in GENERAL_COUNT_NOUN_RE.finditer(source):
                    previous_count = chinese_to_int(prev.group(1))
                    previous_unit = prev.group(2)
                    previous_noun = prev.group(3)
                    if previous_count is None or previous_count < 2:
                        continue
                    if previous_unit == "字":
                        continue
                    previous_label = canonical_count_label(previous_unit, previous_noun)
                    if previous_label != label:
                        continue
                    nearest = {
                        "index": back + 1,
                        "count": previous_count,
                        "unit": previous_unit,
                        "noun": previous_noun,
                        "phrase": prev.group(0),
                        "paragraph": paragraphs[back],
                    }
                if nearest:
                    break

            if nearest and nearest["count"] != current_count:
                issues.append(
                    {
                        "index": idx + 1,
                        "reference": match.group(0),
                        "expected_from_previous": nearest["count"],
                        "actual_in_current": current_count,
                        "label": label,
                        "previous_index": nearest["index"],
                        "previous_phrase": nearest["phrase"],
                        "previous_paragraph": nearest["paragraph"],
                        "paragraph": para,
                    }
                )
    return issues


def has_flashback_cue(text: str) -> bool:
    return any(cue in text for cue in FLASHBACK_CUES)


def extract_time_markers(text: str) -> list[dict[str, object]]:
    markers: list[dict[str, object]] = []
    for literal, value, label in TIME_LITERAL_MARKERS:
        for match in re.finditer(re.escape(literal), text):
            markers.append(
                {
                    "label": label,
                    "value": value,
                    "start": match.start(),
                }
            )

    for match in RELATIVE_DAY_RE.finditer(text):
        offset = chinese_to_int(match.group(1))
        if offset is None:
            continue
        markers.append(
            {
                "label": match.group(0),
                "value": offset * 2,
                "start": match.start(),
            }
        )

    for match in HALF_MONTH_RE.finditer(text):
        markers.append(
            {
                "label": match.group(0),
                "value": 15 * 2,
                "start": match.start(),
            }
        )

    for match in RELATIVE_MONTH_RE.finditer(text):
        offset = chinese_to_int(match.group(1))
        if offset is None:
            continue
        markers.append(
            {
                "label": match.group(0),
                "value": offset * 30 * 2,
                "start": match.start(),
            }
        )

    return sorted(markers, key=lambda item: item["start"])


def find_time_regressions(paragraphs: list[str]) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    last_marker: dict[str, object] | None = None

    for idx, para in enumerate(paragraphs, start=1):
        if has_flashback_cue(para):
            continue
        markers = extract_time_markers(para)
        if not markers:
            continue
        current_marker = markers[-1]
        if last_marker and current_marker["value"] < last_marker["value"]:
            issues.append(
                {
                    "index": idx,
                    "label": current_marker["label"],
                    "paragraph": para,
                    "previous_index": last_marker["index"],
                    "previous_label": last_marker["label"],
                    "previous_paragraph": last_marker["paragraph"],
                }
            )
        last_marker = {
            "index": idx,
            "label": current_marker["label"],
            "value": current_marker["value"],
            "paragraph": para,
        }
    return issues


def find_title_conflicts(paragraphs: list[str], lookback: int = 6) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    seen_by_base: dict[str, list[dict[str, object]]] = defaultdict(list)

    for idx, para in enumerate(paragraphs, start=1):
        for match in NAME_TITLE_RE.finditer(para):
            base = match.group(1)
            title = match.group(2)
            cluster = TITLE_CLUSTER_MAP.get(title)
            if cluster is None:
                continue

            current = {
                "index": idx,
                "base": base,
                "title": title,
                "cluster": cluster,
                "paragraph": para,
            }

            for previous in reversed(seen_by_base[base]):
                if idx - previous["index"] > lookback:
                    break
                if previous["title"] == title:
                    continue
                pair = frozenset((previous["cluster"], cluster))
                if pair not in INCOMPATIBLE_TITLE_CLUSTERS:
                    continue
                issues.append(
                    {
                        "index": idx,
                        "base": base,
                        "title": title,
                        "cluster": cluster,
                        "paragraph": para,
                        "previous_index": previous["index"],
                        "previous_title": previous["title"],
                        "previous_cluster": previous["cluster"],
                        "previous_paragraph": previous["paragraph"],
                    }
                )
                break

            seen_by_base[base].append(current)

    return issues


def find_identity_conflicts(paragraphs: list[str], lookback: int = 8) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    seen_by_base: dict[str, list[dict[str, object]]] = defaultdict(list)

    for idx, para in enumerate(paragraphs, start=1):
        for match in IDENTITY_NOUN_RE.finditer(para):
            base = match.group(1)
            identity = match.group(2)
            cluster = IDENTITY_CLUSTER_MAP.get(identity)
            if cluster is None:
                continue

            current = {
                "index": idx,
                "base": base,
                "identity": identity,
                "cluster": cluster,
                "paragraph": para,
            }

            for previous in reversed(seen_by_base[base]):
                if idx - previous["index"] > lookback:
                    break
                if previous["identity"] == identity:
                    continue
                pair = frozenset((previous["cluster"], cluster))
                if pair not in INCOMPATIBLE_IDENTITY_CLUSTERS:
                    continue
                issues.append(
                    {
                        "index": idx,
                        "base": base,
                        "identity": identity,
                        "paragraph": para,
                        "previous_index": previous["index"],
                        "previous_identity": previous["identity"],
                        "previous_paragraph": previous["paragraph"],
                    }
                )
                break

            seen_by_base[base].append(current)

    return issues


def extract_static_locations(paragraph: str) -> list[str]:
    locations = [match.group(1) for match in STATIC_LOCATION_RE.finditer(paragraph)]
    lead = LEADING_LOCATION_RE.match(paragraph)
    if lead:
        locations.append(lead.group(1))
    return locations


def locations_related(left: str, right: str) -> bool:
    return left == right or left in right or right in left


def has_movement_cue(text: str) -> bool:
    return any(cue in text for cue in MOVEMENT_CUES)


def find_location_conflicts(paragraphs: list[str], lookback: int = 2) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    last_static: dict[str, object] | None = None

    for idx, para in enumerate(paragraphs, start=1):
        if has_flashback_cue(para):
            continue
        locations = extract_static_locations(para)
        if not locations:
            continue
        current = locations[-1]
        if last_static and idx - last_static["index"] <= lookback:
            if not locations_related(last_static["location"], current) and not has_movement_cue(para):
                issues.append(
                    {
                        "index": idx,
                        "location": current,
                        "paragraph": para,
                        "previous_index": last_static["index"],
                        "previous_location": last_static["location"],
                        "previous_paragraph": last_static["paragraph"],
                    }
                )
        last_static = {
            "index": idx,
            "location": current,
            "paragraph": para,
        }
    return issues


def extract_object_state_events(paragraph: str) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []

    def all_positions(text: str, needle: str) -> list[int]:
        positions = []
        start = 0
        while True:
            idx = text.find(needle, start)
            if idx == -1:
                return positions
            positions.append(idx)
            start = idx + len(needle)

    seen_pairs = set()
    for raw_object in OBJECT_TERMS:
        canonical = OBJECT_CANONICAL_MAP.get(raw_object, raw_object)
        obj_positions = all_positions(paragraph, raw_object)
        if not obj_positions:
            continue

        for cue in OBJECT_HELD_CUES:
            cue_positions = all_positions(paragraph, cue)
            for obj_pos in obj_positions:
                for cue_pos in cue_positions:
                    if abs(obj_pos - cue_pos) <= 12:
                        key = (canonical, "held", cue, obj_pos, cue_pos)
                        if key in seen_pairs:
                            continue
                        seen_pairs.add(key)
                        left = min(obj_pos, cue_pos)
                        right = max(obj_pos + len(raw_object), cue_pos + len(cue))
                        phrase = paragraph[left:right]
                        events.append({"object": canonical, "state": "held", "phrase": phrase})

        for cue in OBJECT_AWAY_CUES:
            cue_positions = all_positions(paragraph, cue)
            for obj_pos in obj_positions:
                for cue_pos in cue_positions:
                    if abs(obj_pos - cue_pos) <= 12:
                        key = (canonical, "away", cue, obj_pos, cue_pos)
                        if key in seen_pairs:
                            continue
                        seen_pairs.add(key)
                        left = min(obj_pos, cue_pos)
                        right = max(obj_pos + len(raw_object), cue_pos + len(cue))
                        phrase = paragraph[left:right]
                        events.append({"object": canonical, "state": "away", "phrase": phrase})
    return events


def has_reacquire_cue(text: str) -> bool:
    return any(cue in text for cue in OBJECT_REACQUIRE_CUES)


def find_object_state_conflicts(paragraphs: list[str], lookback: int = 3) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    recent_away: dict[str, list[dict[str, object]]] = defaultdict(list)

    for idx, para in enumerate(paragraphs, start=1):
        events = extract_object_state_events(para)
        for event in events:
            if event["state"] == "held":
                for previous in reversed(recent_away[event["object"]]):
                    if idx - previous["index"] > lookback:
                        break
                    if has_reacquire_cue(para):
                        break
                    issues.append(
                        {
                            "index": idx,
                            "object": event["object"],
                            "phrase": event["phrase"],
                            "paragraph": para,
                            "previous_index": previous["index"],
                            "previous_phrase": previous["phrase"],
                            "previous_paragraph": previous["paragraph"],
                        }
                    )
                    break
            elif event["state"] == "away":
                recent_away[event["object"]].append(
                    {
                        "index": idx,
                        "phrase": event["phrase"],
                        "paragraph": para,
                    }
                )

    return issues


def has_healing_cue(text: str) -> bool:
    return any(cue in text for cue in HEALING_CUES)


def find_injury_continuity_issues(paragraphs: list[str], lookback: int = 6) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    recent_injuries: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)

    for idx, para in enumerate(paragraphs, start=1):
        for match in INJURY_STATE_RE.finditer(para):
            name = match.group(1)
            part = match.group(2)
            recent_injuries[(name, part)].append(
                {
                    "index": idx,
                    "phrase": match.group(0),
                    "paragraph": para,
                }
            )

        for match in INJURY_RECOVERY_RE.finditer(para):
            name = match.group(1)
            part = match.group(2)
            key = (name, part)
            for previous in reversed(recent_injuries[key]):
                if idx - previous["index"] > lookback:
                    break
                window = "\n".join(paragraphs[previous["index"] - 1 : idx])
                if has_healing_cue(window):
                    break
                issues.append(
                    {
                        "index": idx,
                        "name": name,
                        "part": part,
                        "phrase": match.group(0),
                        "paragraph": para,
                        "previous_index": previous["index"],
                        "previous_phrase": previous["phrase"],
                        "previous_paragraph": previous["paragraph"],
                    }
                )
                break
    return issues


def has_stock_flow_cue(text: str) -> bool:
    return any(cue in text for cue in STOCK_FLOW_CUES)


def find_inventory_conflicts(paragraphs: list[str], lookback: int = 4) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    recent_stock: dict[str, list[dict[str, object]]] = defaultdict(list)

    for idx, para in enumerate(paragraphs, start=1):
        for match in STOCK_ASSERT_RE.finditer(para):
            count = chinese_to_int(match.group(2))
            resource_text = match.group(3)
            resource = STOCK_RESOURCE_MAP.get(resource_text)
            if count is None or resource is None:
                continue

            for previous in reversed(recent_stock[resource]):
                if idx - previous["index"] > lookback:
                    break
                if previous["count"] == count:
                    break
                window = "\n".join(paragraphs[previous["index"] - 1 : idx])
                if has_stock_flow_cue(window):
                    break
                issues.append(
                    {
                        "index": idx,
                        "resource": resource,
                        "phrase": match.group(0),
                        "count": count,
                        "paragraph": para,
                        "previous_index": previous["index"],
                        "previous_phrase": previous["phrase"],
                        "previous_count": previous["count"],
                        "previous_paragraph": previous["paragraph"],
                    }
                )
                break

            recent_stock[resource].append(
                {
                    "index": idx,
                    "count": count,
                    "phrase": match.group(0),
                    "paragraph": para,
                }
            )
    return issues


def extract_present_names(paragraph: str) -> set[str]:
    names = {match.group(1) for match in NAME_ACTION_RE.finditer(paragraph)}
    names.update(match.group(1) for match in ENTRY_NAME_RE.finditer(paragraph))
    return names


def extract_only_present_set(paragraph: str) -> set[str] | None:
    match_one = ONLY_PRESENT_ONE_RE.search(paragraph)
    if match_one:
        return {match_one.group(1)}
    match_two = ONLY_PRESENT_TWO_RE.search(paragraph)
    if match_two:
        return {match_two.group(1), match_two.group(2)}
    return None


def find_presence_conflicts(paragraphs: list[str], lookback: int = 2) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    recent_only_present: dict[str, object] | None = None
    recent_exit: dict[str, list[dict[str, object]]] = defaultdict(list)

    for idx, para in enumerate(paragraphs, start=1):
        allowed_set = extract_only_present_set(para)
        if allowed_set is not None:
            recent_only_present = {
                "index": idx,
                "allowed": allowed_set,
                "paragraph": para,
            }

        for match in EXIT_NAME_RE.finditer(para):
            recent_exit[match.group(1)].append(
                {
                    "index": idx,
                    "phrase": match.group(0),
                    "paragraph": para,
                }
            )

        entry_names = {match.group(1) for match in ENTRY_NAME_RE.finditer(para)}
        present_names = extract_present_names(para)

        if recent_only_present and idx > recent_only_present["index"] and idx - recent_only_present["index"] <= lookback:
            for name in sorted(present_names):
                if name in recent_only_present["allowed"] or name in entry_names:
                    continue
                issues.append(
                    {
                        "index": idx,
                        "name": name,
                        "paragraph": para,
                        "previous_index": recent_only_present["index"],
                        "previous_phrase": recent_only_present["paragraph"],
                        "type": "only_present",
                    }
                )
                break

        for name in sorted(present_names):
            for previous in reversed(recent_exit[name]):
                if idx - previous["index"] > lookback:
                    break
                if name in entry_names:
                    break
                issues.append(
                    {
                        "index": idx,
                        "name": name,
                        "paragraph": para,
                        "previous_index": previous["index"],
                        "previous_phrase": previous["phrase"],
                        "type": "exit_return",
                    }
                )
                break

    return issues


def contains_named_speech(paragraph: str) -> bool:
    return bool(NAME_SPEECH_BEFORE_RE.search(paragraph) or NAME_SPEECH_AFTER_RE.search(paragraph))


def normalize_name_token(token: str) -> str:
    while len(token) > 2 and token[-1] in NAME_TRAILING_PARTICLES:
        token = token[:-1]
    return token


def is_probable_name(token: str) -> bool:
    token = normalize_name_token(token)
    if len(token) < 2 or len(token) > 4:
        return False
    if token in NON_NAME_TOKENS:
        return False
    if any(token.startswith(prefix) for prefix in NON_NAME_PREFIXES):
        return False
    if any(part in token for part in NON_NAME_PARTS):
        return False
    return True


def extract_named_dialogues_from_paragraph(paragraph: str, index: int) -> list[dict[str, object]]:
    dialogues: list[dict[str, object]] = []
    for match in NAME_SPEECH_BEFORE_RE.finditer(paragraph):
        name = normalize_name_token(match.group(1))
        if not is_probable_name(name):
            continue
        dialogues.append(
            {
                "index": index,
                "name": name,
                "quote": match.group(2),
                "paragraph": paragraph,
            }
        )
    for match in NAME_SPEECH_AFTER_RE.finditer(paragraph):
        name = normalize_name_token(match.group(2))
        if not is_probable_name(name):
            continue
        dialogues.append(
            {
                "index": index,
                "name": name,
                "quote": match.group(1),
                "paragraph": paragraph,
            }
        )
    return dialogues


def extract_named_dialogues(paragraphs: list[str]) -> list[dict[str, object]]:
    dialogues: list[dict[str, object]] = []
    for idx, para in enumerate(paragraphs, start=1):
        dialogues.extend(extract_named_dialogues_from_paragraph(para, idx))
    dialogues.sort(key=lambda item: (item["index"], item["name"], item["quote"]))
    return dialogues


def find_dialogue_attribution_issues(paragraphs: list[str], run_threshold: int = 7) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    quote_run_start: int | None = None
    quote_run_samples: list[tuple[int, str]] = []

    for idx, para in enumerate(paragraphs, start=1):
        quote_count = len(QUOTE_CONTENT_RE.findall(para))
        speech_names = {
            item["name"] for item in extract_named_dialogues_from_paragraph(para, idx)
        }

        if quote_count == 1 and len(speech_names) >= 2:
            issues.append(
                {
                    "type": "dual_speaker_single_quote",
                    "index": idx,
                    "names": sorted(speech_names),
                    "paragraph": para,
                }
            )

        if QUOTE_ONLY_RE.match(para) and not contains_named_speech(para):
            if quote_run_start is None:
                quote_run_start = idx
                quote_run_samples = []
            quote_run_samples.append((idx, para))
            continue

        if quote_run_start is not None and len(quote_run_samples) >= run_threshold:
            issues.append(
                {
                    "type": "bare_quote_run",
                    "start_index": quote_run_start,
                    "end_index": quote_run_samples[-1][0],
                    "samples": quote_run_samples[:4],
                }
            )
        quote_run_start = None
        quote_run_samples = []

    if quote_run_start is not None and len(quote_run_samples) >= run_threshold:
        issues.append(
            {
                "type": "bare_quote_run",
                "start_index": quote_run_start,
                "end_index": quote_run_samples[-1][0],
                "samples": quote_run_samples[:4],
            }
        )

    return issues


def has_voice_soften_cue(text: str) -> bool:
    return any(cue in text for cue in VOICE_SOFTEN_CUES)


def classify_quote_style(quote: str) -> str | None:
    formal_score = 0
    formal_score += sum(marker in quote for marker in FORMAL_STRONG_MARKERS) * 2
    formal_score += sum(marker in quote for marker in FORMAL_WEAK_MARKERS)
    colloquial_score = sum(marker in quote for marker in COLLOQUIAL_MARKERS)

    if formal_score >= 2 and colloquial_score == 0:
        return "formal"
    if colloquial_score >= 1 and formal_score == 0:
        return "colloquial"
    return None


def find_voice_shift_issues(paragraphs: list[str], lookback: int = 24) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    recent_styles: dict[str, list[dict[str, object]]] = defaultdict(list)

    for item in extract_named_dialogues(paragraphs):
        style = classify_quote_style(item["quote"])
        if style is None:
            continue

        name = item["name"]
        idx = item["index"]
        for previous in reversed(recent_styles[name]):
            if idx - previous["index"] > lookback:
                break
            if previous["style"] == style:
                break
            if has_voice_soften_cue(previous["paragraph"]) or has_voice_soften_cue(item["paragraph"]):
                break
            issues.append(
                {
                    "index": idx,
                    "name": name,
                    "style": style,
                    "quote": item["quote"],
                    "paragraph": item["paragraph"],
                    "previous_index": previous["index"],
                    "previous_style": previous["style"],
                    "previous_quote": previous["quote"],
                    "previous_paragraph": previous["paragraph"],
                }
            )
            break

        recent_styles[name].append(
            {
                "index": idx,
                "style": style,
                "quote": item["quote"],
                "paragraph": item["paragraph"],
            }
        )

    return issues


def paragraph_has_task_signal(paragraph: str, cues: tuple[str, ...]) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    matched_cues = [cue for cue in cues if cue in paragraph]
    if not matched_cues:
        return hits
    for topic, keywords in TASK_TOPIC_KEYWORDS.items():
        for keyword in keywords:
            if keyword in paragraph:
                hits.append(
                    {
                        "topic": topic,
                        "keyword": keyword,
                        "cue": matched_cues[0],
                    }
                )
                break
    return hits


def has_task_setback_cue(text: str) -> bool:
    return any(cue in text for cue in TASK_SETBACK_CUES)


def find_resolved_task_regressions(paragraphs: list[str], lookback: int = 10) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    recent_resolved: dict[str, list[dict[str, object]]] = defaultdict(list)

    for idx, para in enumerate(paragraphs, start=1):
        problem_signals = paragraph_has_task_signal(para, TASK_PROBLEM_CUES)
        for signal in problem_signals:
            topic = signal["topic"]
            for previous in reversed(recent_resolved[topic]):
                if idx - previous["index"] > lookback:
                    break
                window = "\n".join(paragraphs[previous["index"] - 1 : idx])
                if has_task_setback_cue(window):
                    break
                issues.append(
                    {
                        "index": idx,
                        "topic": topic,
                        "keyword": signal["keyword"],
                        "cue": signal["cue"],
                        "paragraph": para,
                        "previous_index": previous["index"],
                        "previous_keyword": previous["keyword"],
                        "previous_cue": previous["cue"],
                        "previous_paragraph": previous["paragraph"],
                    }
                )
                break

        resolved_signals = paragraph_has_task_signal(para, TASK_RESOLVED_CUES)
        for signal in resolved_signals:
            recent_resolved[signal["topic"]].append(
                {
                    "index": idx,
                    "keyword": signal["keyword"],
                    "cue": signal["cue"],
                    "paragraph": para,
                }
            )

    return issues


def has_dialogue_resume_cue(text: str) -> bool:
    return any(cue in text for cue in DIALOGUE_RESUME_CUES)


def find_dialogue_action_chain_issues(paragraphs: list[str], lookback: int = 2) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    recent_silence: dict[str, list[dict[str, object]]] = defaultdict(list)

    for idx, para in enumerate(paragraphs, start=1):
        for match in SILENCE_STATE_RE.finditer(para):
            name = normalize_name_token(match.group(1))
            if not is_probable_name(name):
                continue
            recent_silence[name].append(
                {
                    "index": idx,
                    "phrase": match.group(0),
                    "paragraph": para,
                }
            )

        for dialogue in extract_named_dialogues_from_paragraph(para, idx):
            name = dialogue["name"]
            for previous in reversed(recent_silence[name]):
                if idx - previous["index"] > lookback:
                    break
                window = "\n".join(paragraphs[previous["index"] - 1 : idx])
                if has_dialogue_resume_cue(window):
                    break
                issues.append(
                    {
                        "index": idx,
                        "name": name,
                        "quote": dialogue["quote"],
                        "paragraph": para,
                        "previous_index": previous["index"],
                        "previous_phrase": previous["phrase"],
                        "previous_paragraph": previous["paragraph"],
                    }
                )
                break

    return issues


def is_probable_pov_holder(token: str) -> bool:
    return is_probable_name(token) and token not in POV_HOLDER_STOPWORDS


def has_pov_shift_cue(text: str) -> bool:
    return any(cue in text for cue in POV_SHIFT_CUES)


def extract_inner_pov_holders(paragraph: str) -> list[str]:
    holders: list[str] = []
    seen = set()
    for match in POV_INNER_STATE_RE.finditer(paragraph):
        name = normalize_name_token(match.group(1))
        if not is_probable_pov_holder(name):
            continue
        if name in seen:
            continue
        seen.add(name)
        holders.append(name)
    return holders


def find_pov_breach_issues(paragraphs: list[str], lookback: int = 2) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    last_holder: dict[str, object] | None = None

    for idx, para in enumerate(paragraphs, start=1):
        holders = extract_inner_pov_holders(para)
        if len(holders) >= 2 and not has_pov_shift_cue(para):
            issues.append(
                {
                    "type": "same_paragraph",
                    "index": idx,
                    "holders": holders,
                    "paragraph": para,
                }
            )

        if len(holders) == 1:
            current = holders[0]
            if last_holder and current != last_holder["name"] and idx - last_holder["index"] <= lookback:
                window = "\n".join(paragraphs[last_holder["index"] - 1 : idx])
                if not has_pov_shift_cue(window):
                    issues.append(
                        {
                            "type": "adjacent_shift",
                            "index": idx,
                            "name": current,
                            "paragraph": para,
                            "previous_index": last_holder["index"],
                            "previous_name": last_holder["name"],
                            "previous_paragraph": last_holder["paragraph"],
                        }
                    )
            last_holder = {
                "index": idx,
                "name": current,
                "paragraph": para,
            }

    return issues


def extract_relation_temperature_events(paragraph: str) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []

    for pattern in RELATION_WARM_PATTERNS:
        for match in pattern.finditer(paragraph):
            left = normalize_name_token(match.group(1))
            right = normalize_name_token(match.group(2))
            if not (is_probable_name(left) and is_probable_name(right)) or left == right:
                continue
            events.append(
                {
                    "state": "warm",
                    "left": left,
                    "right": right,
                    "phrase": match.group(0),
                }
            )

    for pattern in RELATION_ROLLBACK_PATTERNS:
        for match in pattern.finditer(paragraph):
            left = normalize_name_token(match.group(1))
            right = normalize_name_token(match.group(2))
            if not (is_probable_name(left) and is_probable_name(right)) or left == right:
                continue
            events.append(
                {
                    "state": "rollback",
                    "left": left,
                    "right": right,
                    "phrase": match.group(0),
                }
            )

    return events


def relation_pair_key(left: str, right: str) -> tuple[str, str]:
    return tuple(sorted((left, right)))


def has_relation_setback_cue(text: str) -> bool:
    return any(cue in text for cue in RELATION_SETBACK_CUES)


def find_relation_temperature_regressions(paragraphs: list[str], lookback: int = 12) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    recent_warm: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)

    for idx, para in enumerate(paragraphs, start=1):
        events = extract_relation_temperature_events(para)
        for event in events:
            pair = relation_pair_key(event["left"], event["right"])
            if event["state"] == "rollback":
                for previous in reversed(recent_warm[pair]):
                    if idx - previous["index"] > lookback:
                        break
                    window = "\n".join(paragraphs[previous["index"] - 1 : idx])
                    if has_relation_setback_cue(window):
                        break
                    issues.append(
                        {
                            "index": idx,
                            "pair": pair,
                            "phrase": event["phrase"],
                            "paragraph": para,
                            "previous_index": previous["index"],
                            "previous_phrase": previous["phrase"],
                            "previous_paragraph": previous["paragraph"],
                        }
                    )
                    break
            elif event["state"] == "warm":
                recent_warm[pair].append(
                    {
                        "index": idx,
                        "phrase": event["phrase"],
                        "paragraph": para,
                    }
                )

    return issues


def has_event_bridge_cue(text: str) -> bool:
    return any(cue in text for cue in EVENT_BRIDGE_CUES)


def find_event_causality_breaks(paragraphs: list[str], lookback: int = 2) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    recent_pending: dict[str, list[dict[str, object]]] = defaultdict(list)

    for idx, para in enumerate(paragraphs, start=1):
        for topic, pattern in EVENT_GATE_PENDING_PATTERNS:
            for match in pattern.finditer(para):
                recent_pending[topic].append(
                    {
                        "index": idx,
                        "key": normalize_name_token(match.group(1)),
                        "phrase": match.group(0),
                        "paragraph": para,
                    }
                )

        for topic, pattern in EVENT_GATE_RESOLVED_PATTERNS:
            for match in pattern.finditer(para):
                current_key = normalize_name_token(match.group(1))
                for previous in reversed(recent_pending[topic]):
                    if idx - previous["index"] > lookback:
                        break
                    if current_key and previous["key"] and current_key != previous["key"]:
                        continue
                    window = "\n".join(paragraphs[previous["index"] - 1 : idx])
                    if has_event_bridge_cue(window):
                        break
                    issues.append(
                        {
                            "index": idx,
                            "topic": topic,
                            "phrase": match.group(0),
                            "paragraph": para,
                            "previous_index": previous["index"],
                            "previous_phrase": previous["phrase"],
                            "previous_paragraph": previous["paragraph"],
                        }
                    )
                    break

    return issues


def has_world_constant_change_cue(text: str) -> bool:
    return any(cue in text for cue in WORLD_CONSTANT_CHANGE_CUES)


def find_world_constant_conflicts(paragraphs: list[str], lookback: int = 10) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    seen_constants: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)

    for idx, para in enumerate(paragraphs, start=1):
        for match in WORLD_CONSTANT_ASSERT_RE.finditer(para):
            subject = normalize_name_token(match.group(1))
            count = chinese_to_int(match.group(2))
            unit = match.group(3)
            if count is None:
                continue
            key = (subject, unit)
            for previous in reversed(seen_constants[key]):
                if idx - previous["index"] > lookback:
                    break
                if previous["count"] == count:
                    break
                window = "\n".join(paragraphs[previous["index"] - 1 : idx])
                if has_world_constant_change_cue(window):
                    break
                issues.append(
                    {
                        "index": idx,
                        "subject": subject,
                        "unit": unit,
                        "count": count,
                        "phrase": match.group(0),
                        "paragraph": para,
                        "previous_index": previous["index"],
                        "previous_count": previous["count"],
                        "previous_phrase": previous["phrase"],
                        "previous_paragraph": previous["paragraph"],
                    }
                )
                break
            seen_constants[key].append(
                {
                    "index": idx,
                    "count": count,
                    "phrase": match.group(0),
                    "paragraph": para,
                }
            )

    return issues


def parse_outline_entries(outline_path: Path | None) -> list[dict[str, object]]:
    if outline_path is None or not outline_path.exists():
        return []
    paragraphs, _ = read_text(outline_path)
    entries: list[dict[str, object]] = []
    for para in paragraphs:
        match = OUTLINE_LINE_RE.match(para)
        if not match:
            continue
        chapter_no = chinese_to_int(match.group(1))
        if chapter_no is None:
            continue
        content = match.group(2).strip()
        if not content:
            continue
        entries.append(
            {
                "chapter_no": chapter_no,
                "text": content,
            }
        )
    return entries


def extract_outline_segments(text: str) -> list[str]:
    body = re.sub(r"^[：:、\-—\s]+", "", text)
    parts = re.split(r"[，。！？；：:]", body)
    segments = []
    seen = set()
    for part in parts:
        segment = normalize(part)
        if len(segment) < 6 or len(segment) > 22:
            continue
        if segment in seen:
            continue
        seen.add(segment)
        segments.append(part.strip())
    return segments


def find_outline_premature_nodes(
    paragraphs: list[str], outline_path: Path | None, chapter_no: int | None, gap: int = 3
) -> list[dict[str, object]]:
    if chapter_no is None:
        return []
    issues: list[dict[str, object]] = []
    outline_entries = parse_outline_entries(outline_path)
    future_entries = [entry for entry in outline_entries if entry["chapter_no"] >= chapter_no + gap]

    for idx, para in enumerate(paragraphs, start=1):
        normalized_para = normalize(para)
        if len(normalized_para) < 10:
            continue
        for entry in future_entries:
            for segment in extract_outline_segments(entry["text"]):
                if normalize(segment) in normalized_para:
                    issues.append(
                        {
                            "index": idx,
                            "future_chapter": entry["chapter_no"],
                            "segment": segment,
                            "paragraph": para,
                            "outline_text": entry["text"],
                        }
                    )
                    if len(issues) >= 8:
                        return issues
                    break
    return issues


def has_permission_grant_cue(text: str) -> bool:
    return any(cue in text for cue in PERMISSION_GRANT_CUES)


def find_permission_boundary_conflicts(paragraphs: list[str], lookback: int = 6) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    denied_actions: dict[str, list[dict[str, object]]] = defaultdict(list)

    for idx, para in enumerate(paragraphs, start=1):
        for action, pattern in PERMISSION_DENIAL_PATTERNS:
            for match in pattern.finditer(para):
                actor = normalize_name_token(match.group(1))
                if not is_probable_name(actor):
                    continue
                denied_actions[action].append(
                    {
                        "index": idx,
                        "actor": actor,
                        "phrase": match.group(0),
                        "paragraph": para,
                    }
                )

        for action, pattern in PERMISSION_ACTION_PATTERNS:
            for match in pattern.finditer(para):
                actor = normalize_name_token(match.group(1))
                if not is_probable_name(actor):
                    continue
                for previous in reversed(denied_actions[action]):
                    if idx - previous["index"] > lookback:
                        break
                    if actor != previous["actor"]:
                        continue
                    window = "\n".join(paragraphs[previous["index"] - 1 : idx])
                    if has_permission_grant_cue(window):
                        break
                    issues.append(
                        {
                            "index": idx,
                            "actor": actor,
                            "action": action,
                            "phrase": match.group(0),
                            "paragraph": para,
                            "previous_index": previous["index"],
                            "previous_phrase": previous["phrase"],
                            "previous_paragraph": previous["paragraph"],
                        }
                    )
                    break

    return issues


def collect_chapter_payloads(current_path: Path, current_paragraphs: list[str], previous_files: list[Path]) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for path in previous_files:
        paragraphs, _ = read_text(path)
        if not paragraphs:
            continue
        payloads.append(
            {
                "path": str(path),
                "chapter_no": detect_chapter_number(paragraphs[0], path),
                "paragraphs": paragraphs[1:],
            }
        )
    payloads.append(
        {
            "path": str(current_path),
            "chapter_no": detect_chapter_number(current_paragraphs[0], current_path),
            "paragraphs": current_paragraphs[1:],
        }
    )
    return sorted(payloads, key=lambda item: item["chapter_no"] or 0)


def canonicalize_foreshadow_topic(text: str) -> str | None:
    for pattern, canonical in FORESHADOW_CANONICAL_PATTERNS:
        if pattern.search(text):
            return canonical
    return None


def find_foreshadow_gap_warnings(
    chapter_payloads: list[dict[str, object]], current_no: int | None, gap_threshold: int = 4
) -> list[dict[str, object]]:
    if current_no is None:
        return []
    issues: list[dict[str, object]] = []
    plants: list[dict[str, object]] = []
    seen = set()

    for payload in chapter_payloads:
        chapter_no = payload["chapter_no"]
        if chapter_no is None or chapter_no >= current_no:
            continue
        for idx, para in enumerate(payload["paragraphs"], start=1):
            for pattern in FORESHADOW_PLANT_PATTERNS:
                for match in pattern.finditer(para):
                    topic = canonicalize_foreshadow_topic(match.group(1))
                    if not topic:
                        continue
                    key = (chapter_no, topic)
                    if key in seen:
                        continue
                    seen.add(key)
                    plants.append(
                        {
                            "chapter_no": chapter_no,
                            "index": idx,
                            "topic": topic,
                            "phrase": match.group(0),
                            "paragraph": para,
                        }
                    )

    for plant in plants:
        if current_no - plant["chapter_no"] < gap_threshold:
            continue
        revisited = False
        for payload in chapter_payloads:
            chapter_no = payload["chapter_no"]
            if chapter_no is None or chapter_no <= plant["chapter_no"]:
                continue
            for para in payload["paragraphs"]:
                if plant["topic"] in para and any(cue in para for cue in FORESHADOW_REVISIT_CUES):
                    revisited = True
                    break
            if revisited:
                break
        if not revisited:
            issues.append(plant)
    return issues[:8]


def normalize_goal_phrase(text: str) -> str:
    text = re.sub(r"^(先|得先|先得|把|将|去|要去)", "", text)
    text = re.sub(r"(这件事|这一关|这一步)$", "", text)
    return text


def extract_goal_pendings(paragraph: str) -> list[str]:
    goals: list[str] = []
    seen = set()
    for pattern in GOAL_PENDING_PATTERNS:
        for match in pattern.finditer(paragraph):
            goal = normalize_goal_phrase(match.group(1))
            if len(normalize(goal)) < 2 or len(normalize(goal)) > 12:
                continue
            if goal in seen:
                continue
            seen.add(goal)
            goals.append(goal)
    return goals


def find_stage_goal_idle_warnings(
    chapter_payloads: list[dict[str, object]], current_no: int | None, repeat_threshold: int = 3, recent_window: int = 4
) -> list[dict[str, object]]:
    if current_no is None:
        return []
    recent_payloads = [payload for payload in chapter_payloads if payload["chapter_no"] and current_no - payload["chapter_no"] < recent_window]
    goal_mentions: dict[str, list[dict[str, object]]] = defaultdict(list)
    progress_seen: dict[str, bool] = defaultdict(bool)

    for payload in recent_payloads:
        chapter_no = payload["chapter_no"]
        for idx, para in enumerate(payload["paragraphs"], start=1):
            for goal in extract_goal_pendings(para):
                goal_mentions[goal].append(
                    {
                        "chapter_no": chapter_no,
                        "index": idx,
                        "paragraph": para,
                    }
                )
            for goal in list(goal_mentions.keys()):
                if goal in para and any(cue in para for cue in GOAL_PROGRESS_CUES):
                    progress_seen[goal] = True

    issues: list[dict[str, object]] = []
    for goal, mentions in goal_mentions.items():
        chapter_set = sorted({item["chapter_no"] for item in mentions if item["chapter_no"] is not None})
        if len(chapter_set) < repeat_threshold:
            continue
        if progress_seen[goal]:
            continue
        latest = mentions[-1]
        issues.append(
            {
                "goal": goal,
                "chapters": chapter_set,
                "index": latest["index"],
                "paragraph": latest["paragraph"],
            }
        )
    return issues[:8]


def canonicalize_char_resource(unit_text: str) -> str:
    mapping = {
        "两银子": "silver",
        "两银": "silver",
        "银子": "silver",
        "文钱": "copper",
        "铜钱": "copper",
        "包药": "medicine",
        "包药材": "medicine",
        "袋粮": "grain",
        "袋米": "grain",
        "斤米": "grain",
        "块饼": "food",
        "张饼": "food",
        "块干粮": "food",
        "壶水": "water",
        "袋盐": "salt",
        "包盐": "salt",
    }
    return mapping.get(unit_text, unit_text)


def has_char_resource_replenish_cue(text: str) -> bool:
    return any(cue in text for cue in CHAR_RESOURCE_REPLENISH_CUES)


def find_character_resource_closure_issues(paragraphs: list[str], lookback: int = 6) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    low_resources: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)

    for idx, para in enumerate(paragraphs, start=1):
        for pattern in (CHAR_RESOURCE_LOW_RE, CHAR_RESOURCE_LAST_RE):
            for match in pattern.finditer(para):
                actor = normalize_name_token(match.group(1))
                if not is_probable_name(actor):
                    continue
                amount = chinese_to_int(match.group(2))
                resource = canonicalize_char_resource(match.group(3))
                if amount is None:
                    continue
                low_resources[(actor, resource)].append(
                    {
                        "index": idx,
                        "available": amount,
                        "spent": 0,
                        "phrase": match.group(0),
                        "paragraph": para,
                    }
                )

        for match in CHAR_RESOURCE_SPEND_RE.finditer(para):
            actor = normalize_name_token(match.group(1))
            if not is_probable_name(actor):
                continue
            spend_amount = chinese_to_int(match.group(2)) if match.group(2) else 1
            resource = canonicalize_char_resource(match.group(3))
            if spend_amount is None:
                continue
            for previous in reversed(low_resources[(actor, resource)]):
                if idx - previous["index"] > lookback:
                    break
                window = "\n".join(paragraphs[previous["index"] - 1 : idx])
                if has_char_resource_replenish_cue(window):
                    break
                previous["spent"] += spend_amount
                if previous["spent"] > previous["available"]:
                    issues.append(
                        {
                            "index": idx,
                            "actor": actor,
                            "resource": resource,
                            "phrase": match.group(0),
                            "paragraph": para,
                            "previous_index": previous["index"],
                            "previous_phrase": previous["phrase"],
                            "previous_paragraph": previous["paragraph"],
                            "available": previous["available"],
                            "spent": previous["spent"],
                        }
                    )
                break

    return issues


def canonicalize_promise_topic(text: str) -> str | None:
    for pattern, canonical in PROMISE_TOPIC_PATTERNS:
        if pattern.search(text):
            return canonical
    return None


def find_promise_timeout_warnings(
    chapter_payloads: list[dict[str, object]], current_no: int | None, gap_threshold: int = 3
) -> list[dict[str, object]]:
    if current_no is None:
        return []
    promises: list[dict[str, object]] = []
    issues: list[dict[str, object]] = []

    for payload in chapter_payloads:
        chapter_no = payload["chapter_no"]
        if chapter_no is None or chapter_no >= current_no:
            continue
        for idx, para in enumerate(payload["paragraphs"], start=1):
            if not any(cue in para for cue in PROMISE_DEADLINE_CUES):
                continue
            if not any(cue in para for cue in PROMISE_COMMIT_CUES):
                continue
            topic = canonicalize_promise_topic(para)
            if not topic:
                continue
            promises.append(
                {
                    "chapter_no": chapter_no,
                    "index": idx,
                    "topic": topic,
                    "phrase": para,
                }
            )

    for promise in promises:
        if current_no - promise["chapter_no"] < gap_threshold:
            continue
        fulfilled = False
        for payload in chapter_payloads:
            chapter_no = payload["chapter_no"]
            if chapter_no is None or chapter_no <= promise["chapter_no"]:
                continue
            for para in payload["paragraphs"]:
                if promise["topic"] in para and any(cue in para for cue in PROMISE_FULFILL_CUES):
                    fulfilled = True
                    break
            if fulfilled:
                break
        if not fulfilled:
            issues.append(promise)

    return issues[:8]


def extract_priority_goals(paragraph: str) -> list[str]:
    goals: list[str] = []
    seen = set()
    for pattern in PRIORITY_GOAL_PATTERNS:
        for match in pattern.finditer(paragraph):
            goal = normalize_goal_phrase(match.group(1))
            if len(normalize(goal)) < 2 or len(normalize(goal)) > 12:
                continue
            if goal in seen:
                continue
            seen.add(goal)
            goals.append(goal)
    return goals


def has_priority_reset_cue(text: str) -> bool:
    return any(cue in text for cue in PRIORITY_RESET_CUES)


def find_parallel_priority_disorder_warnings(
    chapter_payloads: list[dict[str, object]], current_no: int | None, gap_threshold: int = 2
) -> list[dict[str, object]]:
    if current_no is None:
        return []
    declarations: list[dict[str, object]] = []
    issues: list[dict[str, object]] = []

    for payload in chapter_payloads:
        chapter_no = payload["chapter_no"]
        if chapter_no is None or chapter_no >= current_no:
            continue
        for idx, para in enumerate(payload["paragraphs"], start=1):
            for goal in extract_priority_goals(para):
                declarations.append(
                    {
                        "chapter_no": chapter_no,
                        "index": idx,
                        "goal": goal,
                        "paragraph": para,
                    }
                )

    for decl in declarations:
        if current_no - decl["chapter_no"] < gap_threshold:
            continue
        diverted_goals: list[str] = []
        progressed = False
        reset = False
        for payload in chapter_payloads:
            chapter_no = payload["chapter_no"]
            if chapter_no is None or chapter_no <= decl["chapter_no"]:
                continue
            for para in payload["paragraphs"]:
                if decl["goal"] in para and any(cue in para for cue in GOAL_PROGRESS_CUES):
                    progressed = True
                    break
                if has_priority_reset_cue(para):
                    reset = True
                for other in extract_goal_pendings(para):
                    if other != decl["goal"] and other not in diverted_goals:
                        diverted_goals.append(other)
            if progressed:
                break
        if progressed or reset:
            continue
        if len(diverted_goals) >= 2:
            issues.append(
                {
                    "chapter_no": decl["chapter_no"],
                    "index": decl["index"],
                    "goal": decl["goal"],
                    "paragraph": decl["paragraph"],
                    "diverted_goals": diverted_goals[:4],
                }
            )

    return issues[:8]


def has_stance_switch_cue(text: str) -> bool:
    return any(cue in text for cue in STANCE_SWITCH_CUES)


def normalize_stance_target(token: str) -> str:
    return normalize_name_token(token).rstrip("这那")


def is_probable_stance_target(token: str) -> bool:
    if token in STANCE_TARGET_STOPWORDS:
        return False
    if any(token.endswith(suffix) for suffix in STANCE_TARGET_SUFFIXES):
        return False
    return is_probable_name(token)


def extract_stance_events(paragraph: str) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []

    for pattern in STANCE_SUPPORT_PATTERNS:
        for match in pattern.finditer(paragraph):
            actor = normalize_name_token(match.group(1))
            target = normalize_stance_target(match.group(2))
            if not (is_probable_name(actor) and is_probable_stance_target(target)) or actor == target:
                continue
            events.append(
                {
                    "state": "support",
                    "actor": actor,
                    "target": target,
                    "phrase": match.group(0),
                }
            )

    for pattern in STANCE_OPPOSE_PATTERNS:
        for match in pattern.finditer(paragraph):
            actor = normalize_name_token(match.group(1))
            target = normalize_stance_target(match.group(2))
            if not (is_probable_name(actor) and is_probable_stance_target(target)) or actor == target:
                continue
            events.append(
                {
                    "state": "oppose",
                    "actor": actor,
                    "target": target,
                    "phrase": match.group(0),
                }
            )

    return events


def find_stance_flip_flop_warnings(
    chapter_payloads: list[dict[str, object]], current_no: int | None, lookback: int = 6
) -> list[dict[str, object]]:
    if current_no is None:
        return []
    issues: list[dict[str, object]] = []
    stance_history: dict[str, list[dict[str, object]]] = defaultdict(list)

    for payload in chapter_payloads:
        chapter_no = payload["chapter_no"]
        if chapter_no is None or chapter_no > current_no:
            continue
        for idx, para in enumerate(payload["paragraphs"], start=1):
            for event in extract_stance_events(para):
                actor = event["actor"]
                for previous in reversed(stance_history[actor]):
                    if chapter_no - previous["chapter_no"] > lookback:
                        break
                    if previous["target"] == event["target"] and previous["state"] == event["state"]:
                        break
                    window = previous["paragraph"] + "\n" + para
                    if has_stance_switch_cue(window):
                        break
                    issues.append(
                        {
                            "chapter_no": chapter_no,
                            "index": idx,
                            "actor": actor,
                            "target": event["target"],
                            "state": event["state"],
                            "phrase": event["phrase"],
                            "paragraph": para,
                            "previous_chapter": previous["chapter_no"],
                            "previous_index": previous["index"],
                            "previous_target": previous["target"],
                            "previous_state": previous["state"],
                            "previous_phrase": previous["phrase"],
                            "previous_paragraph": previous["paragraph"],
                        }
                    )
                    break
                stance_history[actor].append(
                    {
                        "chapter_no": chapter_no,
                        "index": idx,
                        "state": event["state"],
                        "target": event["target"],
                        "phrase": event["phrase"],
                        "paragraph": para,
                    }
                )

    return issues[:8]


def count_reveal_density_cues(paragraph: str) -> int:
    return sum(paragraph.count(cue) for cue in REVEAL_DENSITY_CUES)


def find_reveal_density_imbalance(paragraphs: list[str]) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []

    for idx, para in enumerate(paragraphs, start=1):
        cue_count = count_reveal_density_cues(para)
        if cue_count >= 2:
            issues.append(
                {
                    "type": "single_paragraph",
                    "index": idx,
                    "count": cue_count,
                    "paragraph": para,
                }
            )

    for start in range(len(paragraphs) - 2):
        window = paragraphs[start : start + 3]
        total = sum(count_reveal_density_cues(para) for para in window)
        if total >= 4:
            issues.append(
                {
                    "type": "three_paragraph_window",
                    "start_index": start + 1,
                    "end_index": start + 3,
                    "count": total,
                    "samples": window,
                }
            )
            break

    return issues[:8]


def has_hook_cue(text: str) -> bool:
    return any(cue in text for cue in HOOK_CUES)


def has_flat_end_cue(text: str) -> bool:
    return any(cue in text for cue in FLAT_END_CUES)


def find_ending_hook_failures(paragraphs: list[str]) -> list[dict[str, object]]:
    if not paragraphs:
        return []
    tail = paragraphs[-2:] if len(paragraphs) >= 2 else paragraphs[-1:]
    tail_text = "\n".join(tail)
    if has_hook_cue(tail_text):
        return []
    if not any(has_flat_end_cue(para) for para in tail):
        return []
    return [
        {
            "index": len(paragraphs),
            "paragraph": paragraphs[-1],
            "tail": tail,
        }
    ]


def has_emotion_reaction_cue(text: str) -> bool:
    if any(cue in text for cue in EMOTION_REACTION_CUES):
        return True
    return any(token in text for token in ("什么", "怎么会", "怎么可能", "不可能", "？", "?"))


def find_emotion_reaction_gaps(paragraphs: list[str], lookahead: int = 2) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    if len(paragraphs) <= 2:
        return issues

    last_eligible = max(0, len(paragraphs) - lookahead)
    for idx, para in enumerate(paragraphs[:last_eligible], start=1):
        match_phrase = None
        actor = None
        for pattern in EMOTION_SHOCK_PATTERNS:
            match = pattern.search(para)
            if not match:
                continue
            match_phrase = match.group(0)
            actor = normalize_name_token(match.group(1)) if match.lastindex else None
            if actor and not is_probable_name(actor):
                actor = None
            break
        if not match_phrase:
            continue
        window = "\n".join(paragraphs[idx - 1 : min(len(paragraphs), idx + lookahead)])
        if has_emotion_reaction_cue(window):
            continue
        issues.append(
            {
                "index": idx,
                "actor": actor,
                "phrase": match_phrase,
                "paragraph": para,
            }
        )
    return issues[:8]


def has_decision_cost_cue(text: str) -> bool:
    return any(cue in text for cue in DECISION_COST_CUES)


def find_decision_cost_gaps(paragraphs: list[str], lookahead: int = 1) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []

    for idx, para in enumerate(paragraphs, start=1):
        for pattern in DECISION_PATTERNS:
            for match in pattern.finditer(para):
                window = "\n".join(paragraphs[idx - 1 : min(len(paragraphs), idx + lookahead)])
                if has_decision_cost_cue(window):
                    continue
                actor = normalize_name_token(match.group(1))
                if not is_probable_name(actor):
                    actor = None
                issues.append(
                    {
                        "index": idx,
                        "actor": actor,
                        "decision": match.group(0),
                        "goal": match.group(2),
                        "paragraph": para,
                    }
                )
                if len(issues) >= 8:
                    return issues
    return issues


def chapter_title_stub(title: str) -> str:
    match = TITLE_RE.match(title.strip())
    if not match:
        return title.strip()
    parts = title.split(maxsplit=1)
    if len(parts) == 2:
        return parts[1].strip()
    return title.strip()


def prepare_outline_focus_segments(text: str, title: str | None = None) -> list[str]:
    segments = extract_outline_segments(text)
    if not segments:
        segments = [text.strip()]
    if not segments and title:
        segments = [chapter_title_stub(title)]

    deduped: list[str] = []
    seen = set()
    for segment in segments:
        key = normalize(segment)
        if 3 <= len(key) <= 12 and key not in seen:
            seen.add(key)
            deduped.append(segment.strip())

        for size in range(2, min(6, len(key)) + 1):
            for start in range(0, len(key) - size + 1):
                candidate = key[start : start + size]
                if candidate in FOCUS_TERM_STOPWORDS:
                    continue
                if candidate[0] in FOCUS_TERM_EDGE_CHARS or candidate[-1] in FOCUS_TERM_EDGE_CHARS:
                    continue
                if len(candidate) == 2 and candidate[-1] not in FOCUS_TERM_ANCHOR_TAILS:
                    continue
                if candidate in seen:
                    continue
                seen.add(candidate)
                deduped.append(candidate)

    return deduped


def matched_focus_terms(paragraph: str, terms: list[str]) -> list[str]:
    paragraph_key = normalize(paragraph)
    hits: list[str] = []
    seen = set()
    for term in terms:
        key = normalize(term)
        if key and key in paragraph_key and key not in seen:
            seen.add(key)
            hits.append(term)
    return hits


def longest_overlap_ratio(paragraph: str, segment: str) -> float:
    para_key = normalize(paragraph)
    segment_key = normalize(segment)
    if not para_key or not segment_key:
        return 0.0
    if segment_key in para_key:
        return 1.0
    match = SequenceMatcher(None, segment_key, para_key).find_longest_match(0, len(segment_key), 0, len(para_key))
    return match.size / max(1, len(segment_key))


def best_outline_alignment(paragraph: str, segments: list[str]) -> tuple[float, str | None]:
    best_score = 0.0
    best_segment = None
    for segment in segments:
        score = longest_overlap_ratio(paragraph, segment)
        if score > best_score:
            best_score = score
            best_segment = segment
    return best_score, best_segment


def find_subplot_overrun_warnings(
    paragraphs: list[str],
    outline_path: Path | None,
    chapter_no: int | None,
    title: str,
    nearby_window: int = 2,
) -> list[dict[str, object]]:
    if chapter_no is None:
        return []

    outline_entries = parse_outline_entries(outline_path)
    if not outline_entries:
        return []

    current_entry = next((entry for entry in outline_entries if entry["chapter_no"] == chapter_no), None)
    if current_entry is None:
        return []

    current_segments = prepare_outline_focus_segments(current_entry["text"], title=title)
    if not current_segments:
        return []

    nearby_entries = [entry for entry in outline_entries if 0 < abs(entry["chapter_no"] - chapter_no) <= nearby_window]
    if not nearby_entries:
        return []

    other_segments = {
        entry["chapter_no"]: prepare_outline_focus_segments(entry["text"])
        for entry in nearby_entries
    }
    other_segments = {chapter: segments for chapter, segments in other_segments.items() if segments}
    if not other_segments:
        return []

    main_hits: list[dict[str, object]] = []
    off_hits: dict[int, list[dict[str, object]]] = defaultdict(list)

    for idx, para in enumerate(paragraphs, start=1):
        if len(normalize(para)) < 12:
            continue
        current_matches = matched_focus_terms(para, current_segments)
        current_score, current_segment = best_outline_alignment(para, current_segments)
        if current_matches or current_score >= 0.45:
            main_hits.append(
                {
                    "index": idx,
                    "score": round(current_score, 3),
                    "segment": current_segment or (current_matches[0] if current_matches else None),
                    "matches": current_matches[:4],
                }
            )

        best_other_score = 0.0
        best_other_chapter = None
        best_other_segment = None
        best_other_matches: list[str] = []
        for other_chapter, segments in other_segments.items():
            matches = matched_focus_terms(para, segments)
            score, segment = best_outline_alignment(para, segments)
            if len(matches) > len(best_other_matches) or (len(matches) == len(best_other_matches) and score > best_other_score):
                best_other_score = score
                best_other_chapter = other_chapter
                best_other_segment = segment
                best_other_matches = matches

        if (
            best_other_chapter is not None
            and (best_other_matches or best_other_segment)
            and len(best_other_matches) >= 2
            and len(best_other_matches) >= len(current_matches) + 2
        ):
            off_hits[best_other_chapter].append(
                {
                    "index": idx,
                    "score": round(best_other_score, 3),
                    "segment": best_other_segment or best_other_matches[0],
                    "matches": best_other_matches[:4],
                    "paragraph": para,
                }
            )

    if not off_hits:
        return []

    top_chapter, top_hits = max(off_hits.items(), key=lambda item: len(item[1]))
    if len(top_hits) < 3:
        return []
    if len(top_hits) <= len(main_hits) + 1:
        return []

    other_entry = next((entry for entry in nearby_entries if entry["chapter_no"] == top_chapter), None)
    if other_entry is None:
        return []

    return [
        {
            "chapter_no": chapter_no,
            "main_hit_count": len(main_hits),
            "other_chapter": top_chapter,
            "other_hit_count": len(top_hits),
            "current_outline": current_entry["text"],
            "other_outline": other_entry["text"],
            "samples": top_hits[:3],
        }
    ]


def collect_previous_files(current_no: int | None, previous_dir: Path | None, explicit: list[Path]) -> list[Path]:
    files = list(explicit)
    if previous_dir and previous_dir.exists():
        candidates = sorted(
            [p for p in previous_dir.iterdir() if p.is_file() and p.suffix.lower() in {".docx", ".md", ".txt"}]
        )
        for path in candidates:
            file_no = detect_chapter_number(path.stem, path)
            if current_no is None or file_no is None:
                continue
            if file_no < current_no:
                files.append(path)
    deduped = []
    seen = set()
    for path in files:
        resolved = str(path.resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(path)
    return sorted(deduped, key=lambda p: detect_chapter_number(p.stem, p) or 0)


def find_previous_overlaps(
    current_paragraphs: list[str],
    previous_files: list[Path],
    threshold: float,
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, object] | None]:
    exact_hits: list[dict[str, object]] = []
    near_hits: list[dict[str, object]] = []
    latest_prev_summary: dict[str, object] | None = None

    previous_maps: dict[str, list[tuple[Path, int, str]]] = defaultdict(list)
    previous_payloads: list[tuple[Path, list[str]]] = []

    for path in previous_files:
        paragraphs, _ = read_text(path)
        previous_payloads.append((path, paragraphs))
        for idx, para in enumerate(paragraphs, start=1):
            key = normalize(para)
            if len(key) < 25:
                continue
            previous_maps[key].append((path, idx, para))

    for idx, para in enumerate(current_paragraphs, start=1):
        key = normalize(para)
        if len(key) < 25:
            continue
        for path, prev_idx, sample in previous_maps.get(key, []):
            exact_hits.append(
                {
                    "current_index": idx,
                    "previous_file": str(path),
                    "previous_index": prev_idx,
                    "sample": sample,
                }
            )

    recent_previous = previous_payloads[-3:]
    for idx, para in enumerate(current_paragraphs, start=1):
        if len(normalize(para)) < 80:
            continue
        for path, paragraphs in recent_previous:
            for prev_idx, previous_para in enumerate(paragraphs, start=1):
                if len(normalize(previous_para)) < 80:
                    continue
                ratio = similarity(para, previous_para)
                if ratio >= threshold:
                    near_hits.append(
                        {
                            "current_index": idx,
                            "previous_file": str(path),
                            "previous_index": prev_idx,
                            "ratio": round(ratio, 3),
                            "current_sample": para,
                            "previous_sample": previous_para,
                        }
                    )
                    if len(near_hits) >= 8:
                        break
            if len(near_hits) >= 8:
                break
        if len(near_hits) >= 8:
            break

    if previous_payloads:
        latest_path, latest_paragraphs = previous_payloads[-1]
        latest_prev_summary = {
            "file": str(latest_path),
            "paragraphs": latest_paragraphs,
        }
    return exact_hits, near_hits, latest_prev_summary


def recent_recap_overlap(
    current_paragraphs: list[str], latest_previous: dict[str, object] | None, recent_window: int
) -> list[dict[str, object]]:
    if not latest_previous:
        return []
    previous_paragraphs = latest_previous["paragraphs"]
    current_window = current_paragraphs[:recent_window]
    previous_window = previous_paragraphs[-recent_window:]
    overlaps = []
    for idx, para in enumerate(current_window, start=1):
        best_ratio = 0.0
        best_prev_idx = None
        best_prev_sample = None
        for prev_offset, previous_para in enumerate(previous_window, start=max(1, len(previous_paragraphs) - recent_window + 1)):
            ratio = similarity(para, previous_para)
            if ratio > best_ratio:
                best_ratio = ratio
                best_prev_idx = prev_offset
                best_prev_sample = previous_para
        if best_ratio >= 0.78:
            overlaps.append(
                {
                    "current_index": idx,
                    "previous_file": latest_previous["file"],
                    "previous_index": best_prev_idx,
                    "ratio": round(best_ratio, 3),
                    "current_sample": para,
                    "previous_sample": best_prev_sample,
                }
            )
    return overlaps


def locate_outline_entry(outline_path: Path | None, chapter_no: int | None, title: str) -> list[str]:
    if outline_path is None or not outline_path.exists():
        return []
    paragraphs, _ = read_text(outline_path)
    if chapter_no is None:
        return [para for para in paragraphs if title in para][:3]
    patterns = [f"第{chapter_no}章", f"第{int_to_chinese(chapter_no)}章"]
    matched = [para for para in paragraphs if any(pattern in para for pattern in patterns)]
    return matched[:3]


def build_report(args: argparse.Namespace) -> dict[str, object]:
    chapter_path = Path(args.chapter)
    if not chapter_path.exists():
        raise FileNotFoundError(f"找不到章节文件: {chapter_path}")

    rule_paths = [Path(path) for path in args.rules]
    rules = parse_rules(rule_paths)
    paragraphs, raw_text = read_text(chapter_path)
    if not paragraphs:
        raise ValueError("章节内容为空，无法校验")

    title = paragraphs[0]
    body_paragraphs = paragraphs[1:]
    chapter_no = detect_chapter_number(title, chapter_path)
    body_chars = count_body_chars(body_paragraphs)

    title_ok = bool(TITLE_RE.match(title))
    links = URL_RE.findall(raw_text)
    html_hits = HTML_RE.findall(raw_text)
    bad_chars = BAD_CHAR_RE.findall(raw_text)
    exact_duplicates = find_exact_duplicates(body_paragraphs)
    near_duplicates = find_near_duplicates(body_paragraphs, args.near_threshold)
    count_reference_mismatches = find_count_reference_mismatches(body_paragraphs)
    quantity_reference_mismatches = find_quantity_reference_mismatches(body_paragraphs)
    time_regressions = find_time_regressions(body_paragraphs)
    title_conflicts = find_title_conflicts(body_paragraphs)
    identity_conflicts = find_identity_conflicts(body_paragraphs)
    location_conflicts = find_location_conflicts(body_paragraphs)
    object_state_conflicts = find_object_state_conflicts(body_paragraphs)
    injury_continuity_issues = find_injury_continuity_issues(body_paragraphs)
    inventory_conflicts = find_inventory_conflicts(body_paragraphs)
    presence_conflicts = find_presence_conflicts(body_paragraphs)
    dialogue_attribution_issues = find_dialogue_attribution_issues(body_paragraphs)
    voice_shift_issues = find_voice_shift_issues(body_paragraphs)
    resolved_task_regressions = find_resolved_task_regressions(body_paragraphs)
    dialogue_action_chain_issues = find_dialogue_action_chain_issues(body_paragraphs)
    pov_breach_issues = find_pov_breach_issues(body_paragraphs)
    relation_temperature_regressions = find_relation_temperature_regressions(body_paragraphs)
    event_causality_breaks = find_event_causality_breaks(body_paragraphs)
    world_constant_conflicts = find_world_constant_conflicts(body_paragraphs)
    permission_boundary_conflicts = find_permission_boundary_conflicts(body_paragraphs)
    character_resource_closure_issues = find_character_resource_closure_issues(body_paragraphs)
    reveal_density_imbalance = find_reveal_density_imbalance(body_paragraphs)
    ending_hook_failures = find_ending_hook_failures(body_paragraphs)

    previous_files = collect_previous_files(
        current_no=chapter_no,
        previous_dir=Path(args.previous_dir) if args.previous_dir else None,
        explicit=[Path(path) for path in args.previous],
    )
    chapter_payloads = collect_chapter_payloads(chapter_path, paragraphs, previous_files)
    stance_flip_flop_warnings = find_stance_flip_flop_warnings(chapter_payloads, chapter_no)
    foreshadow_gap_warnings = find_foreshadow_gap_warnings(chapter_payloads, chapter_no)
    stage_goal_idle_warnings = find_stage_goal_idle_warnings(chapter_payloads, chapter_no)
    promise_timeout_warnings = find_promise_timeout_warnings(chapter_payloads, chapter_no)
    parallel_priority_disorder_warnings = find_parallel_priority_disorder_warnings(chapter_payloads, chapter_no)
    prev_exact_hits, prev_near_hits, latest_previous = find_previous_overlaps(
        current_paragraphs=body_paragraphs,
        previous_files=previous_files,
        threshold=args.near_threshold,
    )
    recap_hits = recent_recap_overlap(body_paragraphs, latest_previous, args.recent_window)
    outline_path = Path(args.outline) if args.outline else None
    outline_entries = locate_outline_entry(outline_path, chapter_no, title)
    outline_premature_nodes = find_outline_premature_nodes(body_paragraphs, outline_path, chapter_no)
    emotion_reaction_gaps = find_emotion_reaction_gaps(body_paragraphs)
    decision_cost_gaps = find_decision_cost_gaps(body_paragraphs)
    subplot_overrun_warnings = find_subplot_overrun_warnings(body_paragraphs, outline_path, chapter_no, title)

    paragraph_lengths = [len(normalize(para)) for para in body_paragraphs]
    long_paragraphs = [
        {"index": idx + 1, "chars": length, "sample": body_paragraphs[idx]}
        for idx, length in enumerate(paragraph_lengths)
        if length >= 180
    ][:8]

    failures = []
    warnings = []
    passes = []

    if title_ok:
        passes.append("标题格式符合 `第X章 XXXXX`")
    else:
        failures.append("标题格式不符合 `第X章 XXXXX`")

    if body_chars < rules.absolute_min:
        failures.append(f"正文字数 {body_chars}，低于最低要求 {rules.absolute_min}")
    elif body_chars > rules.target_max:
        failures.append(f"正文字数 {body_chars}，超出目标上限 {rules.target_max}")
    elif body_chars < rules.target_min:
        warnings.append(f"正文字数 {body_chars}，高于最低要求但低于目标区间 {rules.target_min}-{rules.target_max}")
    else:
        passes.append(f"正文字数 {body_chars}，位于目标区间 {rules.target_min}-{rules.target_max}")

    if links:
        failures.append(f"检测到外链痕迹 {len(links)} 处")
    else:
        passes.append("未发现外链")

    if html_hits:
        failures.append(f"检测到 HTML 痕迹 {len(html_hits)} 处")
    else:
        passes.append("未发现 HTML 痕迹")

    if bad_chars:
        failures.append(f"检测到乱码替代字符 {len(bad_chars)} 处")
    else:
        passes.append("未发现乱码替代字符")

    if count_reference_mismatches:
        failures.append(f"检测到 {len(count_reference_mismatches)} 处显式字数指代不一致")
    else:
        passes.append("未发现显式字数指代不一致")

    if quantity_reference_mismatches:
        failures.append(f"检测到 {len(quantity_reference_mismatches)} 处显式数量指代不一致")
    else:
        passes.append("未发现显式数量指代不一致")

    if time_regressions:
        warnings.append(f"检测到 {len(time_regressions)} 处显式时间顺序可能回退")
    else:
        passes.append("未发现显式时间顺序回退")

    if title_conflicts:
        warnings.append(f"检测到 {len(title_conflicts)} 处称谓组可能冲突")
    else:
        passes.append("未发现高风险称谓组冲突")

    if identity_conflicts:
        warnings.append(f"检测到 {len(identity_conflicts)} 处身份设定可能冲突")
    else:
        passes.append("未发现高风险身份设定冲突")

    if location_conflicts:
        warnings.append(f"检测到 {len(location_conflicts)} 处场景位置可能跳变")
    else:
        passes.append("未发现显式场景位置跳变")

    if object_state_conflicts:
        warnings.append(f"检测到 {len(object_state_conflicts)} 处物件状态可能冲突")
    else:
        passes.append("未发现显式物件状态冲突")

    if injury_continuity_issues:
        warnings.append(f"检测到 {len(injury_continuity_issues)} 处人物伤势连续性可能冲突")
    else:
        passes.append("未发现显式人物伤势连续性冲突")

    if inventory_conflicts:
        warnings.append(f"检测到 {len(inventory_conflicts)} 处钱粮库存连续性可能冲突")
    else:
        passes.append("未发现显式钱粮库存连续性冲突")

    if presence_conflicts:
        warnings.append(f"检测到 {len(presence_conflicts)} 处出场人物在场性可能冲突")
    else:
        passes.append("未发现显式出场人物在场性冲突")

    if dialogue_attribution_issues:
        warnings.append(f"检测到 {len(dialogue_attribution_issues)} 处对话归属可能错位")
    else:
        passes.append("未发现高风险对话归属错位")

    if voice_shift_issues:
        warnings.append(f"检测到 {len(voice_shift_issues)} 处角色口吻可能突变")
    else:
        passes.append("未发现高风险角色口吻突变")

    if resolved_task_regressions:
        warnings.append(f"检测到 {len(resolved_task_regressions)} 处已解决任务被重复当首难题重写")
    else:
        passes.append("未发现已解决任务被重复当首难题重写")

    if dialogue_action_chain_issues:
        warnings.append(f"检测到 {len(dialogue_action_chain_issues)} 处对话动作链可能断裂")
    else:
        passes.append("未发现高风险对话动作链断裂")

    if pov_breach_issues:
        warnings.append(f"检测到 {len(pov_breach_issues)} 处视角可能越界")
    else:
        passes.append("未发现高风险视角越界")

    if relation_temperature_regressions:
        warnings.append(f"检测到 {len(relation_temperature_regressions)} 处关系温度可能回退")
    else:
        passes.append("未发现高风险关系温度回退")

    if event_causality_breaks:
        warnings.append(f"检测到 {len(event_causality_breaks)} 处事件因果可能断裂")
    else:
        passes.append("未发现高风险事件因果断裂")

    if world_constant_conflicts:
        warnings.append(f"检测到 {len(world_constant_conflicts)} 处世界观常量可能自撞")
    else:
        passes.append("未发现高风险世界观常量自撞")

    if outline_premature_nodes:
        warnings.append(f"检测到 {len(outline_premature_nodes)} 处大纲节点可能偷跑")
    else:
        passes.append("未发现高风险大纲节点偷跑")

    if permission_boundary_conflicts:
        warnings.append(f"检测到 {len(permission_boundary_conflicts)} 处身份权限边界可能自撞")
    else:
        passes.append("未发现高风险身份权限边界自撞")

    if foreshadow_gap_warnings:
        warnings.append(f"检测到 {len(foreshadow_gap_warnings)} 处伏笔回收可能缺口过大")
    else:
        passes.append("未发现高风险伏笔回收缺口")

    if stage_goal_idle_warnings:
        warnings.append(f"检测到 {len(stage_goal_idle_warnings)} 处阶段目标可能空转")
    else:
        passes.append("未发现高风险阶段目标空转")

    if character_resource_closure_issues:
        warnings.append(f"检测到 {len(character_resource_closure_issues)} 处角色资源消耗可能失闭环")
    else:
        passes.append("未发现高风险角色资源消耗失闭环")

    if promise_timeout_warnings:
        warnings.append(f"检测到 {len(promise_timeout_warnings)} 处承诺兑现可能超时")
    else:
        passes.append("未发现高风险承诺兑现超时")

    if parallel_priority_disorder_warnings:
        warnings.append(f"检测到 {len(parallel_priority_disorder_warnings)} 处多线并行优先级可能错乱")
    else:
        passes.append("未发现高风险多线并行优先级错乱")

    if stance_flip_flop_warnings:
        warnings.append(f"检测到 {len(stance_flip_flop_warnings)} 处角色立场可能反复横跳")
    else:
        passes.append("未发现高风险角色立场反复横跳")

    if reveal_density_imbalance:
        warnings.append(f"检测到 {len(reveal_density_imbalance)} 处信息揭示密度可能失衡")
    else:
        passes.append("未发现高风险信息揭示密度失衡")

    if ending_hook_failures:
        warnings.append(f"检测到 {len(ending_hook_failures)} 处章尾钩子可能失效")
    else:
        passes.append("未发现高风险章尾钩子失效")

    if emotion_reaction_gaps:
        warnings.append(f"检测到 {len(emotion_reaction_gaps)} 处情绪反应可能延迟或缺席")
    else:
        passes.append("未发现高风险情绪反应延迟或缺席")

    if decision_cost_gaps:
        warnings.append(f"检测到 {len(decision_cost_gaps)} 处关键决策可能缺少代价")
    else:
        passes.append("未发现高风险关键决策缺代价")

    if subplot_overrun_warnings:
        warnings.append(f"检测到 {len(subplot_overrun_warnings)} 处支线可能抢占主线")
    else:
        passes.append("未发现高风险支线抢主线")

    if exact_duplicates:
        failures.append(f"当前章节内存在 {len(exact_duplicates)} 组重复段落")
    else:
        passes.append("当前章节内未发现重复段落")

    if near_duplicates:
        warnings.append(f"当前章节内存在 {len(near_duplicates)} 组高相似重复段落")
    else:
        passes.append("当前章节内未发现高相似重复段落")

    if prev_exact_hits:
        failures.append(f"与前文章节存在 {len(prev_exact_hits)} 处完全重复段落")
    else:
        passes.append("未发现与前文章节完全重复的段落")

    if prev_near_hits:
        warnings.append(f"与前文章节存在 {len(prev_near_hits)} 处高相似重复段落")

    if recap_hits:
        warnings.append(f"本章开头与上一章尾段存在 {len(recap_hits)} 处高相似复述")

    if long_paragraphs:
        warnings.append(f"检测到 {len(long_paragraphs)} 个偏长段落，建议复核拆段")
    else:
        passes.append("未发现明显超长段落")

    if outline_entries:
        passes.append("已在大纲/目录中定位到当前章节条目")
    else:
        warnings.append("未在大纲/目录中定位到当前章节条目，需人工确认是否错位")

    numbering = {"current_chapter": chapter_no, "previous_last": None, "continuous": None}
    if previous_files:
        previous_last = previous_files[-1]
        previous_last_no = detect_chapter_number(previous_last.stem, previous_last)
        numbering["previous_last"] = previous_last_no
        if chapter_no is not None and previous_last_no is not None:
            numbering["continuous"] = previous_last_no == chapter_no - 1
            if numbering["continuous"]:
                passes.append("章节编号与上一章连续")
            else:
                warnings.append(f"章节编号可能不连续：上一章识别为 {previous_last_no}，当前章识别为 {chapter_no}")

    overall = "通过"
    if failures:
        overall = "不通过"
    elif warnings:
        overall = "警告"

    return {
        "overall": overall,
        "file": str(chapter_path),
        "title": title,
        "chapter_number": chapter_no,
        "body_chars": body_chars,
        "rules": {
            "target_min": rules.target_min,
            "target_max": rules.target_max,
            "absolute_min": rules.absolute_min,
        },
        "passes": passes,
        "warnings": warnings,
        "failures": failures,
        "outline_entries": outline_entries,
        "numbering": numbering,
        "evidence": {
            "count_reference_mismatches": count_reference_mismatches[:8],
            "quantity_reference_mismatches": quantity_reference_mismatches[:8],
            "time_regressions": time_regressions[:8],
            "title_conflicts": title_conflicts[:8],
            "identity_conflicts": identity_conflicts[:8],
            "location_conflicts": location_conflicts[:8],
            "object_state_conflicts": object_state_conflicts[:8],
            "injury_continuity_issues": injury_continuity_issues[:8],
            "inventory_conflicts": inventory_conflicts[:8],
            "presence_conflicts": presence_conflicts[:8],
            "dialogue_attribution_issues": dialogue_attribution_issues[:8],
            "voice_shift_issues": voice_shift_issues[:8],
            "resolved_task_regressions": resolved_task_regressions[:8],
            "dialogue_action_chain_issues": dialogue_action_chain_issues[:8],
            "pov_breach_issues": pov_breach_issues[:8],
            "relation_temperature_regressions": relation_temperature_regressions[:8],
            "event_causality_breaks": event_causality_breaks[:8],
            "world_constant_conflicts": world_constant_conflicts[:8],
            "outline_premature_nodes": outline_premature_nodes[:8],
            "permission_boundary_conflicts": permission_boundary_conflicts[:8],
            "foreshadow_gap_warnings": foreshadow_gap_warnings[:8],
            "stage_goal_idle_warnings": stage_goal_idle_warnings[:8],
            "character_resource_closure_issues": character_resource_closure_issues[:8],
            "promise_timeout_warnings": promise_timeout_warnings[:8],
            "parallel_priority_disorder_warnings": parallel_priority_disorder_warnings[:8],
            "stance_flip_flop_warnings": stance_flip_flop_warnings[:8],
            "reveal_density_imbalance": reveal_density_imbalance[:8],
            "ending_hook_failures": ending_hook_failures[:8],
            "emotion_reaction_gaps": emotion_reaction_gaps[:8],
            "decision_cost_gaps": decision_cost_gaps[:8],
            "subplot_overrun_warnings": subplot_overrun_warnings[:8],
            "exact_duplicates": exact_duplicates,
            "near_duplicates": near_duplicates,
            "previous_exact_hits": prev_exact_hits[:8],
            "previous_near_hits": prev_near_hits[:8],
            "recent_recap_hits": recap_hits[:8],
            "long_paragraphs": long_paragraphs,
        },
    }


def render_text(report: dict[str, object]) -> str:
    lines = []
    lines.append("章节验收报告")
    lines.append(f"结论：{report['overall']}")
    lines.append(f"文件：{report['file']}")
    lines.append(f"标题：{report['title']}")
    lines.append(f"章节号：{report['chapter_number']}")
    lines.append(f"正文字数：{report['body_chars']}")
    rules = report["rules"]
    lines.append(
        f"规则：目标 {rules['target_min']}-{rules['target_max']}，最低 {rules['absolute_min']}"
    )

    if report["outline_entries"]:
        lines.append("匹配到的大纲条目：")
        for entry in report["outline_entries"]:
            lines.append(f"- {entry}")

    for label in ("failures", "warnings", "passes"):
        items = report[label]
        if not items:
            continue
        title = {
            "failures": "阻塞问题",
            "warnings": "风险警告",
            "passes": "通过项",
        }[label]
        lines.append(f"{title}：")
        for item in items:
            lines.append(f"- {item}")

    evidence = report["evidence"]
    if evidence["count_reference_mismatches"]:
        lines.append("显式字数指代不一致证据：")
        for item in evidence["count_reference_mismatches"][:5]:
            lines.append(
                f"- 当前第{item['index']}段写了“{item['reference']}”，"
                f"但引用的第{item['quote_index']}段引语“{item['quoted_text']}”实际为 {item['actual']} 字"
            )

    if evidence["quantity_reference_mismatches"]:
        lines.append("显式数量指代不一致证据：")
        for item in evidence["quantity_reference_mismatches"][:5]:
            lines.append(
                f"- 当前第{item['index']}段写了“{item['reference']}”，"
                f"但第{item['previous_index']}段同类对象写的是“{item['previous_phrase']}”"
            )

    if evidence["time_regressions"]:
        lines.append("显式时间顺序回退证据：")
        for item in evidence["time_regressions"][:5]:
            lines.append(
                f"- 当前第{item['index']}段写了“{item['label']}”，"
                f"但前面第{item['previous_index']}段已推进到“{item['previous_label']}”"
            )

    if evidence["title_conflicts"]:
        lines.append("高风险称谓组冲突证据：")
        for item in evidence["title_conflicts"][:5]:
            lines.append(
                f"- 当前第{item['index']}段把“{item['base']}”写作“{item['base']}{item['title']}”，"
                f"前面第{item['previous_index']}段则写作“{item['base']}{item['previous_title']}”"
            )

    if evidence["identity_conflicts"]:
        lines.append("高风险身份设定冲突证据：")
        for item in evidence["identity_conflicts"][:5]:
            lines.append(
                f"- 当前第{item['index']}段把“{item['base']}”写作“{item['base']}{item['identity']}”，"
                f"前面第{item['previous_index']}段则写作“{item['base']}{item['previous_identity']}”"
            )

    if evidence["location_conflicts"]:
        lines.append("显式场景位置跳变证据：")
        for item in evidence["location_conflicts"][:5]:
            lines.append(
                f"- 当前第{item['index']}段写人在“{item['location']}”，"
                f"但前面第{item['previous_index']}段还在“{item['previous_location']}”且缺少移动提示"
            )

    if evidence["object_state_conflicts"]:
        lines.append("显式物件状态冲突证据：")
        for item in evidence["object_state_conflicts"][:5]:
            lines.append(
                f"- 当前第{item['index']}段写“{item['phrase']}”，"
                f"但前面第{item['previous_index']}段刚写过“{item['previous_phrase']}”"
            )

    if evidence["injury_continuity_issues"]:
        lines.append("人物伤势连续性冲突证据：")
        for item in evidence["injury_continuity_issues"][:5]:
            lines.append(
                f"- 当前第{item['index']}段写“{item['phrase']}”，"
                f"但前面第{item['previous_index']}段刚写过“{item['previous_phrase']}”"
            )

    if evidence["inventory_conflicts"]:
        lines.append("钱粮库存连续性冲突证据：")
        for item in evidence["inventory_conflicts"][:5]:
            lines.append(
                f"- 当前第{item['index']}段写“{item['phrase']}”，"
                f"但前面第{item['previous_index']}段同资源写的是“{item['previous_phrase']}”"
            )

    if evidence["presence_conflicts"]:
        lines.append("出场人物在场性冲突证据：")
        for item in evidence["presence_conflicts"][:5]:
            if item["type"] == "only_present":
                lines.append(
                    f"- 当前第{item['index']}段出现“{item['name']}”，"
                    f"但前面第{item['previous_index']}段已明确限定场内只剩特定人物"
                )
            else:
                lines.append(
                    f"- 当前第{item['index']}段又出现“{item['name']}”，"
                    f"但前面第{item['previous_index']}段刚写过其退场“{item['previous_phrase']}”"
                )

    if evidence["dialogue_attribution_issues"]:
        lines.append("对话归属错位证据：")
        for item in evidence["dialogue_attribution_issues"][:5]:
            if item["type"] == "dual_speaker_single_quote":
                names = "、".join(item["names"])
                lines.append(
                    f"- 第{item['index']}段同一段引语附近同时出现多个说话者标记：{names}"
                )
            else:
                lines.append(
                    f"- 第{item['start_index']}-{item['end_index']}段连续出现无归属纯对白，"
                    f"容易造成说话人错位"
                )

    if evidence["voice_shift_issues"]:
        lines.append("角色口吻突变证据：")
        for item in evidence["voice_shift_issues"][:5]:
            lines.append(
                f"- “{item['name']}”在第{item['previous_index']}段是 {item['previous_style']} 口吻，"
                f"到第{item['index']}段突然变成 {item['style']} 口吻"
            )

    if evidence["resolved_task_regressions"]:
        lines.append("已解决任务重复当首难题重写证据：")
        for item in evidence["resolved_task_regressions"][:5]:
            lines.append(
                f"- 第{item['previous_index']}段已把“{item['topic']}”写成“{item['previous_cue']}”，"
                f"但第{item['index']}段又把它写回“{item['cue']}”"
            )

    if evidence["dialogue_action_chain_issues"]:
        lines.append("对话动作链断裂证据：")
        for item in evidence["dialogue_action_chain_issues"][:5]:
            lines.append(
                f"- 第{item['previous_index']}段刚写“{item['previous_phrase']}”，"
                f"但第{item['index']}段无过渡又让“{item['name']}”开口"
            )

    if evidence["pov_breach_issues"]:
        lines.append("视角越界证据：")
        for item in evidence["pov_breach_issues"][:5]:
            if item["type"] == "same_paragraph":
                lines.append(
                    f"- 第{item['index']}段同段进入多个角色内心：{'、'.join(item['holders'])}"
                )
            else:
                lines.append(
                    f"- 第{item['previous_index']}段刚进“{item['previous_name']}”内心，"
                    f"第{item['index']}段又直接切到“{item['name']}”内心"
                )

    if evidence["relation_temperature_regressions"]:
        lines.append("关系温度回退证据：")
        for item in evidence["relation_temperature_regressions"][:5]:
            pair = " / ".join(item["pair"])
            lines.append(
                f"- 第{item['previous_index']}段已把“{pair}”写到“{item['previous_phrase']}”，"
                f"但第{item['index']}段又写回“{item['phrase']}”"
            )

    if evidence["event_causality_breaks"]:
        lines.append("事件因果断裂证据：")
        for item in evidence["event_causality_breaks"][:5]:
            lines.append(
                f"- 第{item['previous_index']}段刚写“{item['previous_phrase']}”，"
                f"但第{item['index']}段无补台阶就直接写到“{item['phrase']}”"
            )

    if evidence["world_constant_conflicts"]:
        lines.append("世界观常量自撞证据：")
        for item in evidence["world_constant_conflicts"][:5]:
            lines.append(
                f"- 第{item['previous_index']}段把“{item['subject']}”写成“{item['previous_phrase']}”，"
                f"第{item['index']}段又写成“{item['phrase']}”"
            )

    if evidence["outline_premature_nodes"]:
        lines.append("大纲节点偷跑证据：")
        for item in evidence["outline_premature_nodes"][:5]:
            lines.append(
                f"- 第{item['index']}段直接命中后续第{item['future_chapter']}章大纲短语“{item['segment']}”"
            )

    if evidence["permission_boundary_conflicts"]:
        lines.append("身份权限边界自撞证据：")
        for item in evidence["permission_boundary_conflicts"][:5]:
            lines.append(
                f"- 第{item['previous_index']}段刚写“{item['previous_phrase']}”，"
                f"但第{item['index']}段无获准提示又写到“{item['phrase']}”"
            )

    if evidence["foreshadow_gap_warnings"]:
        lines.append("伏笔回收缺口提醒：")
        for item in evidence["foreshadow_gap_warnings"][:5]:
            lines.append(
                f"- 第{item['chapter_no']}章第{item['index']}段埋下“{item['topic']}”伏笔“{item['phrase']}”，"
                f"到当前章仍未见明确回收"
            )

    if evidence["stage_goal_idle_warnings"]:
        lines.append("阶段目标空转提醒：")
        for item in evidence["stage_goal_idle_warnings"][:5]:
            chapter_list = "、".join(str(ch) for ch in item["chapters"])
            lines.append(
                f"- 目标“{item['goal']}”在第 {chapter_list} 章反复被当作当前要务，但未见明确推进完成"
            )

    if evidence["character_resource_closure_issues"]:
        lines.append("角色资源消耗闭环证据：")
        for item in evidence["character_resource_closure_issues"][:5]:
            lines.append(
                f"- 第{item['previous_index']}段刚写“{item['previous_phrase']}”，"
                f"但到第{item['index']}段累计消耗已超出可用资源"
            )

    if evidence["promise_timeout_warnings"]:
        lines.append("承诺兑现超时提醒：")
        for item in evidence["promise_timeout_warnings"][:5]:
            lines.append(
                f"- 第{item['chapter_no']}章第{item['index']}段曾承诺“{item['topic']}”，到当前章仍未见明确兑现"
            )

    if evidence["parallel_priority_disorder_warnings"]:
        lines.append("多线并行优先级错乱提醒：")
        for item in evidence["parallel_priority_disorder_warnings"][:5]:
            diverted = "、".join(item["diverted_goals"])
            lines.append(
                f"- 第{item['chapter_no']}章第{item['index']}段把“{item['goal']}”定为优先，"
                f"后续却连续转去处理“{diverted}”而未见该线推进"
            )

    if evidence["stance_flip_flop_warnings"]:
        lines.append("角色立场反复横跳证据：")
        for item in evidence["stance_flip_flop_warnings"][:5]:
            previous_desc = "站到" if item["previous_state"] == "support" else "针对"
            current_desc = "站到" if item["state"] == "support" else "针对"
            lines.append(
                f"- 第{item['previous_chapter']}章第{item['previous_index']}段写“{item['actor']}{previous_desc}{item['previous_target']}”，"
                f"到第{item['chapter_no']}章第{item['index']}段又写成“{item['actor']}{current_desc}{item['target']}”"
            )

    if evidence["reveal_density_imbalance"]:
        lines.append("信息揭示密度失衡证据：")
        for item in evidence["reveal_density_imbalance"][:5]:
            if item["type"] == "single_paragraph":
                lines.append(
                    f"- 第{item['index']}段单段出现 {item['count']} 处强揭示词，信息可能堆叠过密"
                )
            else:
                lines.append(
                    f"- 第{item['start_index']}-{item['end_index']}段三段内累计 {item['count']} 处强揭示词，信息可能集中爆出"
                )

    if evidence["ending_hook_failures"]:
        lines.append("章尾钩子失效提醒：")
        for item in evidence["ending_hook_failures"][:5]:
            lines.append(
                f"- 章尾最后一段缺少明确牵引，当前收在“{item['paragraph'][:40]}”"
            )

    if evidence["emotion_reaction_gaps"]:
        lines.append("情绪反应延迟或缺席证据：")
        for item in evidence["emotion_reaction_gaps"][:5]:
            lines.append(
                f"- 第{item['index']}段已发生“{item['phrase']}”这类强冲击事件，"
                f"但近距离段落里未见明确情绪承接"
            )

    if evidence["decision_cost_gaps"]:
        lines.append("关键决策缺代价证据：")
        for item in evidence["decision_cost_gaps"][:5]:
            if item["actor"]:
                lines.append(
                    f"- 第{item['index']}段写“{item['actor']}”已作出“{item['decision']}”的决定，"
                    f"但近距离段落里未见明确成本、风险或交换"
                )
            else:
                lines.append(
                    f"- 第{item['index']}段写出“{item['decision']}”这类关键决定，"
                    f"但近距离段落里未见明确成本、风险或交换"
                )

    if evidence["subplot_overrun_warnings"]:
        lines.append("支线抢主线提醒：")
        for item in evidence["subplot_overrun_warnings"][:5]:
            lines.append(
                f"- 当前第{item['chapter_no']}章正文有 {item['other_hit_count']} 段更贴近第{item['other_chapter']}章的大纲功能，"
                f"而本章主线命中仅 {item['main_hit_count']} 段"
            )
            for sample in item["samples"]:
                lines.append(
                    f"参考：第{sample['index']}段命中“{' / '.join(sample['matches'])}”"
                )

    if evidence["exact_duplicates"]:
        lines.append("当前章内重复段落证据：")
        for item in evidence["exact_duplicates"][:5]:
            lines.append(f"- 段落 {item['indexes']}：{item['sample'][:80]}")

    if evidence["previous_exact_hits"]:
        lines.append("与前文章节完全重复证据：")
        for item in evidence["previous_exact_hits"][:5]:
            lines.append(
                f"- 当前第{item['current_index']}段 与 {item['previous_file']} 第{item['previous_index']}段重复："
                f"{item['sample'][:80]}"
            )

    if evidence["recent_recap_hits"]:
        lines.append("开头复述上一章尾段证据：")
        for item in evidence["recent_recap_hits"][:5]:
            lines.append(
                f"- 当前第{item['current_index']}段 与上一章第{item['previous_index']}段相似度 {item['ratio']}"
            )

    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    try:
        report = build_report(args)
    except Exception as exc:
        print(f"校验失败：{exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_text(report))

    return 0 if report["overall"] != "不通过" else 2


if __name__ == "__main__":
    sys.exit(main())
