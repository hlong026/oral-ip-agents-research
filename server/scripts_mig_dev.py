"""一次性：对 dev 库（server/oral.db）执行 alembic upgrade head（用后删除）"""

import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))
from alembic.config import main as alembic_main  # noqa: E402

alembic_main(argv=["upgrade", "head"])
print("DEV DB UPGRADED")
