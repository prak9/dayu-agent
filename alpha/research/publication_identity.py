"""一版一目标的确定发布身份与远端调和标记。"""

from uuid import NAMESPACE_URL, uuid5


def publication_identifier(revision_id: str, target_id: str) -> str:
    """计算发布身份。参数：不可变版本、固定目标。返回：确定 ID。异常：无。"""
    return "publication_" + uuid5(NAMESPACE_URL, f"alpha:{revision_id}:{target_id}").hex


def publication_marker(publication_id: str) -> str:
    """生成远端可回读标记。参数：发布 ID。返回：正文标记。异常：无。"""
    return f"alpha-publication: {publication_id}"
