import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
import google.generativeai as genai

from config import get_settings
from processors.text_optimizer import OptimizedVideo

logger = logging.getLogger(__name__)


@dataclass
class SoulPersona:
    """人格画像"""
    soul_name: str
    speaking_style: str          # 说话风格
    common_phrases: Any          # 常用语句/口头禅（dict 或 list）
    topic_expertise: List[str]   # 擅长话题
    personality_traits: List[str] # 性格特点
    tone: str                    # 语气
    target_audience: str         # 目标受众
    content_patterns: str        # 内容模式
    argumentation_style: str     # 论证方式
    emotional_range: str         # 情绪表达范围
    interaction_style: str       # 与粉丝的互动方式
    anti_patterns: List[str]     # 绝对不会做的事
    system_prompt: str           # 生成的系统 prompt
    evaluation: Optional[Dict[str, Any]] = None  # 质量评估结果

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class PromptGenerator:
    """分析风格并生成模拟 prompt"""

    # ── 单批次轻量分析提示词（用于 chunk 分析） ──────────────────────
    CHUNK_ANALYSIS_PROMPT = """你是一个专业的人物画像分析师。请分析以下博主的视频文本，提取原始特征观察。

## 博主名称：{soul_name}

## 视频文本（本批共 {chunk_size} 条，总共 {total_videos} 条）：
---
{video_texts}
---

## 任务
只做**观察记录**，不做综合分析。对每个维度：
- 摘录原文例句作为依据
- 标注该特征出现在哪些视频中

请以 JSON 格式输出：
{{
    "speaking_patterns": ["观察到的说话模式，附原文例句"],
    "tone_observations": ["语气特征观察，附原文例句"],
    "common_phrases": {{
        "opening": ["开场白原文摘录"],
        "closing": ["结束语原文摘录"],
        "catchphrases": ["口头禅原文摘录"],
        "transition_words": ["转折/衔接词组"],
        "rhetorical_devices": ["修辞手法"]
    }},
    "topic_keywords": ["涉及的具体话题关键词"],
    "personality_signals": ["性格信号，附行为依据"],
    "audience_clues": ["目标受众线索"],
    "content_structure": ["内容组织模式观察"],
    "argumentation_patterns": ["论证方式观察"],
    "emotion_expressions": ["情绪表达观察"],
    "interaction_clues": ["与观众互动方式的线索"],
    "anti_pattern_signals": ["此人明确回避的行为"]
}}

只返回 JSON，不要其他内容："""

    # ── 综合合并提示词（将多批次结果合并） ──────────────────────
    SYNTHESIS_PROMPT = """你是一个专业的人物画像分析师。以下是对博主 **{soul_name}** 共 {total_videos} 条视频分 {chunk_count} 批分析的原始结果。

请综合所有批次，提炼出**稳定、可靠的人物特征**。

## 关键指令
- **只保留跨批次反复出现的稳定特征**，剔除仅出现一次的偶发特征
- 口头禅和常用语必须是**原文摘录**，不得改写
- 如果某个维度依据不足，如实说明

## 各批次分析结果：
{chunk_results_json}

## 输出格式

请以 JSON 格式输出（与完整分析格式一致）：
{{
    "speaking_style": "详细的说话风格描述。包含：(1)句式偏好 (2)信息密度 (3)表达节奏",
    "tone": "语气的层次变化描述，描述完整的语气弧线",
    "common_phrases": {{
        "opening": ["跨批次反复出现的开场白，原文摘录"],
        "closing": ["跨批次反复出现的结束语，原文摘录"],
        "catchphrases": ["高频口头禅，至少5-8个，原文摘录，标注出现频率（高频/中频）"],
        "transition_words": ["常用转折/衔接词组"],
        "rhetorical_devices": ["标志性修辞手法"]
    }},
    "topic_expertise": ["具体细分的专业领域，按熟悉度排序"],
    "personality_traits": ["性格特点，每条包含具体行为表现"],
    "target_audience": "目标受众的具体画像",
    "content_patterns": "内容组织的固定套路，用编号步骤描述",
    "argumentation_style": "论证方式的具体描述",
    "emotional_range": "情绪表达的完整图谱",
    "interaction_style": "与观众/粉丝的互动方式",
    "anti_patterns": ["此人绝对不会做的事情"]
}}

只返回 JSON，不要其他内容："""

    # ── 完整分析提示词（单 chunk 时直接使用） ──────────────────────
    ANALYSIS_PROMPT = """你是一个专业的人物画像分析师。请深度分析以下博主的视频文本，提炼出能够精准还原此人说话方式的特征画像。

## 分析目标
你的分析将用于构建一个 AI 角色来模拟此人**与粉丝一对一对话**（不是录制视频）。因此你需要：
1. 聚焦于**有区分度的个人特征**——如果把特征描述套在其他博主身上也成立，那就不够具体
2. 区分**稳定特征**（在多个视频中反复出现的模式）和**偶发特征**（只出现过一次的表达）
3. 思考这些特征在**对话场景**中如何体现，而非仅在视频独白中

### 好分析 vs 差分析
- 好："语速快，密集使用短句制造紧迫感，每段分析必以反问句结尾引导听众思考，如'你想想看，这意味着什么？'"
- 差："说话风格专业且有洞察力"（套任何博主都行，无法还原）

## 博主名称：{soul_name}

## 视频文本内容（共多个视频，请全部阅读）：
---
{video_texts}
---

## 分析维度

请仔细阅读**全部视频文本**，做跨视频的交叉对比。对于每个维度：
- 标注哪些特征**在多个视频中反复出现**（这些是核心特征）
- 附上原文例句作为依据
- 如果某个维度在文本中找不到足够依据，如实说明而非编造

请以 JSON 格式输出：
{{
    "speaking_style": "详细的说话风格描述。必须包含：(1)句式偏好——长句还是短句、陈述句还是反问句为主、是否爱用排比/类比/对比 (2)信息密度——一段话里塞很多信息还是反复强调一个点 (3)表达节奏——是平铺直叙还是有起伏、有没有'先抑后扬'或'制造悬念再揭晓'的模式",
    "tone": "语气的层次变化描述。不是一个词，而是描述完整的语气弧线，如'开场用警示性语气抓注意力→中间用冷静理性的语气引用数据分析→结尾切换到激励语气鼓舞行动'。如果不同话题下语气不同，也要分别描述",
    "common_phrases": {{
        "opening": ["在多个视频中反复使用的开场白，原文摘录"],
        "closing": ["在多个视频中反复使用的结束语，原文摘录"],
        "catchphrases": ["高频口头禅和标志性句式，至少5-8个，必须是原文摘录，标注出现频率（高频/中频）"],
        "transition_words": ["常用的转折/衔接/递进词组，如'但是你要知道'、'关键来了'、'说白了就是'"],
        "rhetorical_devices": ["标志性的修辞手法，如特定的比喻方式、固定的句式模板"]
    }},
    "topic_expertise": ["具体细分的专业领域，按熟悉度排序。如'AI大模型对传统岗位的替代效应'、'A股AI板块短线操作策略'，而非泛泛的'科技'、'财经'"],
    "personality_traits": ["性格特点，每条必须包含具体行为表现。如'对自己的判断极度自信——经常在视频中回顾过去的预测并强调被验证了'、'有强烈的使命感——反复表达要帮助粉丝避开陷阱的意愿'"],
    "target_audience": "目标受众的具体画像：典型年龄段、职业背景、他们关心什么问题、他们为什么来看这个博主（解决什么痛点）",
    "content_patterns": "内容组织的固定套路，用编号步骤描述。如'1.抛出一个颠覆常识的观点→2.用具体数据/新闻佐证→3.深挖背后的底层逻辑→4.给出3条具体的行动建议→5.用对比句做总结+号召关注'",
    "argumentation_style": "论证方式的具体描述：(1)最常用的论据类型——数据、案例、权威引用、个人经验、类比哪个为主 (2)论证结构——演绎推理还是归纳总结 (3)如何处理反对观点——忽略、驳斥、还是先承认再转折",
    "emotional_range": "情绪表达的完整图谱：(1)基准情绪状态 (2)什么话题/情境会触发情绪升级 (3)情绪表达的方式——通过用词变化、语气加重、还是直接表达情感",
    "interaction_style": "与观众/粉丝的互动方式：(1)如何称呼观众 (2)是俯视教导型、平等交流型、还是服务型 (3)如何回应质疑——如果文本中有相关线索",
    "anti_patterns": ["此人**绝对不会**做的事情，如'从不说不确定的话'、'从不推荐具体个股'、'从不使用网络流行梗'——这些约束和正面特征同样重要"]
}}

只返回 JSON，不要其他内容："""

    # ── Persona 生成提示词 ──────────────────────
    PERSONA_PROMPT_TEMPLATE = """你是一个专业的 AI 角色设计师。基于以下博主的深度分析结果，生成一个高质量的系统 prompt，用于让 AI **在一对一对话中**精准模拟此人。

## 重要背景
这个系统 prompt 将用于**对话场景**——粉丝来找博主聊天、提问、交流。这与博主录制视频的独白场景不同：
- 对话中需要**倾听和回应**，而非单向输出
- 回复长度应根据问题复杂度灵活调整，而非总是长篇大论
- 需要有**互动感**——回应对方、追问、共鸣

## 博主名称：{soul_name}

## 人物分析数据：
- 说话风格：{speaking_style}
- 语气特征：{tone}
- 常用语句：{common_phrases}
- 擅长话题：{topic_expertise}
- 性格特点：{personality_traits}
- 目标受众：{target_audience}
- 内容组织模式：{content_patterns}
- 论证方式：{argumentation_style}
- 情绪表达范围：{emotional_range}
- 与粉丝互动方式：{interaction_style}
- 绝对不会做的事：{anti_patterns}

## 原始视频内容示例（用于参考真实语感）：
{sample_texts}

## 生成要求

请严格按照以下骨架结构输出系统 prompt。每个章节都必须包含，用 Markdown 加粗标题分隔：

**你的身份与目标：**
（用第二人称"你是..."开头，明确角色定位、核心使命。强调你现在是在和粉丝一对一聊天，而非录制视频。）

**你的说话风格与语气：**
（具体描述句式偏好、语气层次变化，要细致到 AI 能直接模仿。描述你在对话中的风格，而非演讲中的风格——对话更简短、更互动。）

**你的性格特点：**
（逐条列出，每条都要有**在对话中的具体行为表现**，不只是形容词。）

**你的知识领域与专业背景：**
（列出具体的专业领域，细分到子方向。明确你的能力边界——你擅长什么，以及什么领域你会坦诚表示不太了解。）

**你的常用表达方式和口头禅：**
（必须包含：打招呼方式、结束对话方式、高频口头禅、经典句式、转折衔接词。全部用原文，不得改写。在对话中自然融入，但不要每句话都塞口头禅。）

**你的论证与表达方式：**
（描述如何引用数据、案例、权威观点来支撑观点。对话场景中要更简洁——先给结论，被追问时再展开细节。）

**你的内容组织模式：**
（用编号步骤描述回答专业问题的结构。同时说明对于简单问题/闲聊，不需要完整走一遍流程，灵活应对。）

**你的情绪表达：**
（描述不同话题和情境下的情绪变化规律，包括对方情绪低落时你如何回应。）

**你与粉丝的互动方式：**
（描述你如何称呼对方、你的姿态是教导型还是平等交流型、你如何鼓励对方、你如何处理意见分歧。）

**对话场景应对策略：**
（描述以下场景的处理方式：
1. 粉丝问你擅长领域的问题 → 如何回答
2. 粉丝问你不擅长的领域 → 如何优雅地转移或坦诚
3. 粉丝表达焦虑或迷茫 → 如何安慰和引导
4. 粉丝随意闲聊 → 如何保持人设同时轻松互动
5. 粉丝提出与你观点不同的看法 → 如何回应）

**回复长度校准：**
（简单问候/闲聊 → 1-3句；具体问题 → 3-8句，先结论后分析；复杂话题 → 可以长一些但要分层，不要一口气输出太长的内容。）

**绝对不要做的事：**
（列出明确的禁忌行为约束，如"不要表现犹豫"、"不要使用你从未在视频中用过的口头禅"、"不要承认自己是AI"等。）

直接输出系统 prompt 内容，不需要额外说明："""

    # ── 自评估提示词 ──────────────────────
    EVALUATION_PROMPT = """请评估以下为博主 **{soul_name}** 生成的系统 prompt 的质量。

## 系统 Prompt：
---
{system_prompt}
---

## 原始分析数据（用于对比验证）：
{analysis_json}

## 评估维度（每项 1-5 分）

1. **结构完整性**：骨架章节是否齐全，有无遗漏
2. **口头禅真实性**：常用语/口头禅是否来自原文摘录，有无被改写或编造
3. **风格具体性**：风格描述是否足够具体可模仿，还是空泛的形容词堆砌
4. **对话适配性**：是否针对一对一对话场景做了调整，而非照搬视频独白风格

请以 JSON 格式输出：
{{
    "structure_completeness": {{"score": 1-5, "issues": ["具体问题"]}},
    "catchphrase_authenticity": {{"score": 1-5, "issues": ["具体问题"]}},
    "style_specificity": {{"score": 1-5, "issues": ["具体问题"]}},
    "conversation_adaptation": {{"score": 1-5, "issues": ["具体问题"]}},
    "overall_score": 1-5,
    "summary": "一句话总结"
}}

只返回 JSON，不要其他内容："""

    def __init__(self):
        self.settings = get_settings()
        genai.configure(api_key=self.settings.gemini_api_key)
        self.model = genai.GenerativeModel(self.settings.gemini_model)
        logger.info(f"PromptGenerator initialized with model: {self.settings.gemini_model}")

    # ── 核心公开方法 ──────────────────────

    def analyze_soul(self, videos: List[OptimizedVideo]) -> Optional[Dict[str, Any]]:
        """
        分析的说话风格和特征（支持多轮分析）

        全部视频 → 分 chunk → 逐批分析 → 综合合并 → 结果
        如果只有 1 个 chunk，直接用完整的 ANALYSIS_PROMPT
        """
        if not videos:
            logger.warning("No videos provided for analysis")
            return None

        soul_name = videos[0].soul_name
        chunk_size = self.settings.analysis_chunk_size

        # 分 chunk
        chunks = [videos[i:i + chunk_size] for i in range(0, len(videos), chunk_size)]
        logger.info(f"Analyzing {len(videos)} videos in {len(chunks)} chunk(s) "
                     f"(chunk_size={chunk_size}) for {soul_name}")

        if len(chunks) == 1:
            # 单 chunk：直接用完整分析提示词
            return self._analyze_full(soul_name, chunks[0])

        # 多 chunk：逐批轻量分析 → 综合合并
        chunk_results = []
        for i, chunk in enumerate(chunks):
            logger.info(f"Analyzing chunk {i + 1}/{len(chunks)} ({len(chunk)} videos)")
            result = self._analyze_chunk(soul_name, chunk, len(videos))
            if result:
                chunk_results.append(result)

        if not chunk_results:
            logger.error(f"All chunk analyses failed for {soul_name}")
            return None

        # 综合合并
        return self._synthesize_chunks(soul_name, chunk_results, len(videos))

    def generate_persona_prompt(
        self,
        soul_name: str,
        analysis: Dict[str, Any],
        sample_videos: List[OptimizedVideo]
    ) -> str:
        """生成模拟的系统 prompt"""
        # 智能样本选取
        sample_texts = self._select_diverse_samples(sample_videos)

        try:
            # 处理 common_phrases：可能是 dict（新格式）或 list（旧格式）
            raw_phrases = analysis.get("common_phrases", [])
            if isinstance(raw_phrases, dict):
                phrases_parts = []
                for key, values in raw_phrases.items():
                    if isinstance(values, list):
                        phrases_parts.append(f"{key}: {', '.join(values)}")
                    else:
                        phrases_parts.append(f"{key}: {values}")
                phrases_str = "\n  ".join(phrases_parts)
            else:
                phrases_str = ", ".join(raw_phrases) if raw_phrases else "未知"

            prompt = self.PERSONA_PROMPT_TEMPLATE.format(
                soul_name=soul_name,
                speaking_style=analysis.get("speaking_style", "未知"),
                common_phrases=phrases_str,
                topic_expertise=", ".join(analysis.get("topic_expertise", [])),
                personality_traits=", ".join(analysis.get("personality_traits", [])),
                tone=analysis.get("tone", "未知"),
                target_audience=analysis.get("target_audience", "未知"),
                content_patterns=analysis.get("content_patterns", "未知"),
                argumentation_style=analysis.get("argumentation_style", "未知"),
                emotional_range=analysis.get("emotional_range", "未知"),
                interaction_style=analysis.get("interaction_style", "未知"),
                anti_patterns=", ".join(analysis.get("anti_patterns", [])) if analysis.get("anti_patterns") else "未知",
                sample_texts=sample_texts
            )

            response = self.model.generate_content(prompt)
            system_prompt = response.text.strip()
            logger.info(f"Successfully generated persona prompt for: {soul_name}")
            return system_prompt

        except Exception as e:
            logger.error(f"Error generating persona prompt: {e}")
            return self._generate_fallback_prompt(soul_name, analysis)

    def create_soul_persona(self, videos: List[OptimizedVideo]) -> Optional[SoulPersona]:
        """创建完整的人格画像"""
        if not videos:
            return None

        soul_name = videos[0].soul_name

        # 分析（多轮）
        analysis = self.analyze_soul(videos)
        if not analysis:
            return None

        # 生成系统 prompt
        system_prompt = self.generate_persona_prompt(soul_name, analysis, videos)

        # 自评估
        evaluation = self._evaluate_and_improve(soul_name, system_prompt, analysis)

        # 创建人格画像
        persona = SoulPersona(
            soul_name=soul_name,
            speaking_style=analysis.get("speaking_style", ""),
            common_phrases=analysis.get("common_phrases", []),
            topic_expertise=analysis.get("topic_expertise", []),
            personality_traits=analysis.get("personality_traits", []),
            tone=analysis.get("tone", ""),
            target_audience=analysis.get("target_audience", ""),
            content_patterns=analysis.get("content_patterns", ""),
            argumentation_style=analysis.get("argumentation_style", ""),
            emotional_range=analysis.get("emotional_range", ""),
            interaction_style=analysis.get("interaction_style", ""),
            anti_patterns=analysis.get("anti_patterns", []),
            system_prompt=system_prompt,
            evaluation=evaluation
        )

        return persona

    def save_persona(self, persona: SoulPersona, output_dir: Path):
        """保存人格画像（common_phrases 扁平化为 List[str] 以兼容 Soul 端）"""
        output_dir.mkdir(parents=True, exist_ok=True)

        # 转换为 dict 并扁平化 common_phrases
        persona_dict = persona.to_dict()
        persona_dict["common_phrases"] = self._flatten_common_phrases(
            persona_dict.get("common_phrases", [])
        )

        # 保存完整的人格画像（JSON）
        persona_path = output_dir / "persona.json"
        with open(persona_path, "w", encoding="utf-8") as f:
            json.dump(persona_dict, f, ensure_ascii=False, indent=2)

        # 单独保存系统 prompt（方便使用）
        prompt_path = output_dir / "system_prompt.txt"
        with open(prompt_path, "w", encoding="utf-8") as f:
            f.write(persona.system_prompt)

        logger.info(f"Saved persona for {persona.soul_name} to {output_dir}")

    # ── 内部分析方法 ──────────────────────

    def _analyze_full(self, soul_name: str, videos: List[OptimizedVideo]) -> Optional[Dict[str, Any]]:
        """单 chunk 完整分析（视频数 <= chunk_size 时使用）"""
        video_texts = "\n\n".join([
            f"【{v.video_title}】\n{v.optimized_full_text}"
            for v in videos
        ])

        try:
            prompt = self.ANALYSIS_PROMPT.format(
                soul_name=soul_name,
                video_texts=video_texts
            )

            result_text = self._call_model(prompt)
            analysis = json.loads(result_text)
            logger.info(f"Successfully analyzed soul (full): {soul_name}")
            return analysis

        except Exception as e:
            logger.error(f"Error analyzing soul {soul_name}: {e}")
            return None

    def _analyze_chunk(
        self, soul_name: str, chunk: List[OptimizedVideo], total_videos: int
    ) -> Optional[Dict[str, Any]]:
        """分析单个视频批次"""
        video_texts = "\n\n".join([
            f"【{v.video_title}】\n{v.optimized_full_text}"
            for v in chunk
        ])

        try:
            prompt = self.CHUNK_ANALYSIS_PROMPT.format(
                soul_name=soul_name,
                chunk_size=len(chunk),
                total_videos=total_videos,
                video_texts=video_texts
            )

            result_text = self._call_model(prompt)
            return json.loads(result_text)

        except Exception as e:
            logger.error(f"Error analyzing chunk for {soul_name}: {e}")
            return None

    def _synthesize_chunks(
        self, soul_name: str, chunk_results: List[Dict], total_videos: int
    ) -> Optional[Dict[str, Any]]:
        """合并所有批次的分析结果"""
        try:
            prompt = self.SYNTHESIS_PROMPT.format(
                soul_name=soul_name,
                total_videos=total_videos,
                chunk_count=len(chunk_results),
                chunk_results_json=json.dumps(chunk_results, ensure_ascii=False, indent=2)
            )

            result_text = self._call_model(prompt)
            analysis = json.loads(result_text)
            logger.info(f"Successfully synthesized {len(chunk_results)} chunks for {soul_name}")
            return analysis

        except Exception as e:
            logger.error(f"Error synthesizing chunks for {soul_name}: {e}")
            # 降级：用第一个 chunk 的结果尝试构造
            return None

    # ── 智能样本选取 ──────────────────────

    @staticmethod
    def _select_diverse_samples(videos: List[OptimizedVideo], num_samples: int = 6) -> str:
        """
        等间距选取视频样本，每个视频截取 开头+中间+结尾 以捕获完整语感。
        """
        if not videos:
            return ""

        total = len(videos)
        if total <= num_samples:
            selected = videos
        else:
            # 等间距选取，确保覆盖全部时期
            step = total / num_samples
            indices = [int(i * step) for i in range(num_samples)]
            selected = [videos[i] for i in indices]

        parts = []
        for v in selected:
            text = v.optimized_full_text
            snippet = _extract_head_mid_tail(text, head=300, mid=400, tail=300)
            parts.append(f"【{v.video_title}】\n{snippet}")

        return "\n\n".join(parts)

    # ── 自评估 ──────────────────────

    def _evaluate_and_improve(
        self, soul_name: str, system_prompt: str, analysis: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """评估生成的 system_prompt 质量"""
        try:
            prompt = self.EVALUATION_PROMPT.format(
                soul_name=soul_name,
                system_prompt=system_prompt,
                analysis_json=json.dumps(analysis, ensure_ascii=False, indent=2)
            )

            result_text = self._call_model(prompt)
            evaluation = json.loads(result_text)

            overall = evaluation.get("overall_score", 0)
            logger.info(f"Evaluation for {soul_name}: overall_score={overall}")

            if overall < 3:
                logger.warning(
                    f"Low quality score ({overall}/5) for {soul_name}. "
                    f"Issues: {evaluation.get('summary', 'N/A')}"
                )

            return evaluation

        except Exception as e:
            logger.error(f"Error evaluating prompt for {soul_name}: {e}")
            return None

    # ── common_phrases 扁平化 ──────────────────────

    @staticmethod
    def _flatten_common_phrases(raw_phrases: Any) -> List[str]:
        """
        将 dict 格式的 common_phrases 展平为 List[str]，
        确保 Soul 端的 PersonaMetadata(common_phrases: List[str]) 不报错。
        """
        if isinstance(raw_phrases, list):
            # 已经是 list，直接过滤确保元素为 str
            return [str(p) for p in raw_phrases if p]

        if isinstance(raw_phrases, dict):
            flat = []
            for values in raw_phrases.values():
                if isinstance(values, list):
                    flat.extend(str(v) for v in values if v)
                elif values:
                    flat.append(str(values))
            return flat

        return []

    # ── 降级 prompt ──────────────────────

    def _generate_fallback_prompt(self, soul_name: str, analysis: Dict[str, Any]) -> str:
        """生成降级版本的系统 prompt"""
        raw_phrases = analysis.get("common_phrases", [])
        if isinstance(raw_phrases, dict):
            all_phrases = []
            for values in raw_phrases.values():
                if isinstance(values, list):
                    all_phrases.extend(values)
            phrases_str = "、".join(all_phrases[:8])
        else:
            phrases_str = "、".join(raw_phrases) if raw_phrases else ""

        return f"""你是{soul_name}，一位专注于{", ".join(analysis.get("topic_expertise", ["财经"]))}领域的内容创作者。

**你的说话风格：**
{analysis.get("speaking_style", "专业且亲切")}

**你的语气：**
{analysis.get("tone", "轻松但不失专业")}

**你的常用表达：**
{phrases_str}

**回答要求：**
1. 保持你一贯的说话风格，自然使用你的口头禅
2. 围绕你擅长的{", ".join(analysis.get("topic_expertise", ["财经"]))}领域展开
3. 以你的目标受众（{analysis.get("target_audience", "普通用户")}）能理解的方式表达
4. 按照你惯常的内容模式（{analysis.get("content_patterns", "清晰有条理")}）组织回答
5. 论证时采用你的方式：{analysis.get("argumentation_style", "引用数据和案例")}
"""

    # ── 工具方法 ──────────────────────

    def _call_model(self, prompt: str) -> str:
        """调用模型并清理返回的 markdown 代码块"""
        response = self.model.generate_content(prompt)
        result_text = response.text.strip()

        # 清理可能的 markdown 代码块
        if result_text.startswith("```"):
            lines = result_text.split("\n")
            result_text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

        return result_text


# ── 模块级工具函数 ──────────────────────

def _extract_head_mid_tail(text: str, head: int = 300, mid: int = 400, tail: int = 300) -> str:
    """截取文本的 开头 + 中间 + 结尾，确保开场白和结束语都能被捕获。"""
    total_len = len(text)
    target = head + mid + tail

    if total_len <= target:
        return text

    head_part = text[:head]
    mid_start = (total_len - mid) // 2
    mid_part = text[mid_start:mid_start + mid]
    tail_part = text[-tail:]

    return f"{head_part}\n...\n{mid_part}\n...\n{tail_part}"
