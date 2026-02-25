"""用户管理器"""

import random
import uuid
from typing import Dict, List, Optional

from common.exceptions import (
    RegistrationError,
    UserAlreadyExistsError,
    UserNotFoundError,
    VerificationError,
)
from common.logger import get_logger
from common.utils.crypto import hash_text, verify_text
from common.utils.datetime import now
from storage.models.secret_catalog import get_questions
from storage.models.user import SecretAnswer, UserProfile
from storage.repositories.user_repository import UserRepository

logger = get_logger(__name__)


class UserManager:
    """用户管理"""

    def __init__(self):
        self._repo = UserRepository()

    # ── 基础 CRUD（保持兼容） ─────────────────────────

    async def list_users(self) -> List[UserProfile]:
        """获取所有用户"""
        return await self._repo.get_all()

    async def get_user(self, user_id: str) -> UserProfile:
        """获取用户，不存在则抛异常"""
        user = await self._repo.get_by_id(user_id)
        if not user:
            raise UserNotFoundError(f"User not found: {user_id}")
        return user

    async def create_user(self, name: str) -> UserProfile:
        """创建新用户（souldev.html 兼容接口）"""
        user_id = str(uuid.uuid4())
        profile = UserProfile(
            id=user_id, name=name, is_anonymous=False, is_registered=True
        )
        return await self._repo.create(profile)

    async def delete_user(self, user_id: str) -> bool:
        """删除用户"""
        result = await self._repo.delete(user_id)
        if not result:
            raise UserNotFoundError(f"User not found: {user_id}")
        return True

    async def update_last_active(self, user_id: str) -> UserProfile:
        """更新用户最后活跃时间"""
        user = await self.get_user(user_id)
        user.last_active = now()
        return await self._repo.update(user)

    # ── Auth: 创建 ────────────────────────────────────

    async def create_anonymous(self) -> UserProfile:
        """创建匿名用户"""
        user_id = str(uuid.uuid4())
        short_id = user_id[:6]
        profile = UserProfile(
            id=user_id,
            name=f"访客_{short_id}",
            is_anonymous=True,
            is_registered=False,
        )
        return await self._repo.create(profile)

    async def register_user(
        self,
        name: str,
        gender: str,
        passphrase: str,
        secrets: List[Dict],
    ) -> UserProfile:
        """完整注册新用户"""
        existing = await self.find_by_name(name)
        if existing:
            raise RegistrationError(f"用户名已被占用: {name}")

        secret_answers = [
            SecretAnswer(
                question_id=s["question_id"],
                answer_hash=hash_text(s["answer"]),
            )
            for s in secrets
        ]

        user_id = str(uuid.uuid4())
        profile = UserProfile(
            id=user_id,
            name=name,
            gender=gender,
            passphrase_hash=hash_text(passphrase),
            secrets=secret_answers,
            is_anonymous=False,
            is_registered=True,
        )
        return await self._repo.create(profile)

    async def upgrade_user(
        self,
        user_id: str,
        name: str,
        gender: str,
        passphrase: str,
        secrets: List[Dict],
    ) -> UserProfile:
        """匿名用户升级为注册用户"""
        user = await self.get_user(user_id)
        if user.is_registered:
            raise RegistrationError("该用户已经注册")

        existing = await self.find_by_name(name)
        if existing and existing.id != user_id:
            raise RegistrationError(f"用户名已被占用: {name}")

        user.name = name
        user.gender = gender
        user.passphrase_hash = hash_text(passphrase)
        user.secrets = [
            SecretAnswer(
                question_id=s["question_id"],
                answer_hash=hash_text(s["answer"]),
            )
            for s in secrets
        ]
        user.is_anonymous = False
        user.is_registered = True
        return await self._repo.update(user)

    # ── Auth: 查询 ────────────────────────────────────

    async def find_by_name(self, name: str) -> Optional[UserProfile]:
        """按名字查找用户"""
        users = await self._repo.get_all()
        for u in users:
            if u.name == name:
                return u
        return None

    # ── Auth: 验证 ────────────────────────────────────

    async def verify_passphrase(self, user_id: str, passphrase: str) -> bool:
        """验证口令"""
        user = await self.get_user(user_id)
        if not user.passphrase_hash:
            raise VerificationError("该用户未设置口令")
        return verify_text(passphrase, user.passphrase_hash)

    async def get_random_challenge(self, user_id: str) -> Dict:
        """随机抽一道用户已设置的小秘密题"""
        user = await self.get_user(user_id)
        if not user.secrets:
            raise VerificationError("该用户未设置小秘密")

        secret = random.choice(user.secrets)
        questions = get_questions()
        question_map = {q.id: q for q in questions}
        q = question_map.get(secret.question_id)
        if not q:
            raise VerificationError("秘密问题数据异常")

        return {
            "question_id": secret.question_id,
            "question": q.question,
            "category": q.category,
        }

    async def verify_secret(
        self, user_id: str, question_id: str, answer: str
    ) -> bool:
        """验证小秘密答案"""
        user = await self.get_user(user_id)
        for s in user.secrets:
            if s.question_id == question_id:
                return verify_text(answer, s.answer_hash)
        raise VerificationError("未找到对应的秘密问题")
