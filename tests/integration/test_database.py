"""测试数据库初始化与基本 CRUD 操作。"""

import sys
import tempfile
import os
from pathlib import Path

# 添加所有包到 Python 路径
root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root / "packages/contracts/src"))
sys.path.insert(0, str(root / "packages/core/src"))
sys.path.insert(0, str(root / "services/api/src"))

from gss_api.db import init_db
from gss_api.repository import OrderRepository
from gss_contracts import Order, OrderStatus, Plan, Mode


def test_database():
    """测试数据库初始化与基本操作。"""
    
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        db = init_db(f"sqlite:///{db_path}")
        print("✓ 数据库初始化成功")
        
        # 获取会话
        session = next(db.get_session())
        repo = OrderRepository(session)
        
        # 测试创建订单
        order = Order(
            plan=Plan.PLUS,
            billing_country="US",
            mode=Mode(),
            status=OrderStatus.CREATED,
        )
        created = repo.create_order(order, idempotency_key="test-key-001")
        print(f"✓ 订单创建成功: {created.id}")
        
        # 测试查询订单
        fetched = repo.get_order(created.id)
        assert fetched is not None
        assert fetched.id == created.id
        print(f"✓ 订单查询成功: {fetched.status}")
        
        # 测试幂等性
        duplicate = repo.find_by_idempotency("test-key-001")
        assert duplicate is not None
        assert duplicate.id == created.id
        print("✓ 幂等性检查通过")
        
        # 测试状态更新
        updated = repo.update_status(created.id, OrderStatus.PENDING_CHECKOUT)
        assert updated.status == OrderStatus.PENDING_CHECKOUT
        print("✓ 状态更新成功")
        
        # 测试列表查询
        orders = repo.list_orders(limit=10)
        assert len(orders) == 1
        print(f"✓ 列表查询成功: {len(orders)} 条订单")
        
        session.close()
        print("\n✅ 所有数据库测试通过！")


if __name__ == "__main__":
    test_database()
