"""Business queries over authoritative project records."""

VIEWS = {
    'rework-supply': (
        '返工物料追溯',
        '沿返工单核对领用 SKU、库位和复测证据，用于班末交接和缺证补录。',
        ['批次', '返工单', 'SKU', '库位', '触发原因', '状态', '复测测量号', '下一步'],
        """
SELECT l.code,r.id,r.sku,COALESCE(s.bin,'未配置'),r.reason,r.state,r.verification_id,
       CASE WHEN s.sku IS NULL THEN '核对库位' WHEN r.issued_at IS NULL THEN '等待领料'
            WHEN r.verification_id IS NULL THEN '等待补录复测' ELSE '复测已关联' END
FROM rework_issue r JOIN pack_lot l ON l.id=r.lot_id LEFT JOIN material_stock s ON s.sku=r.sku ORDER BY r.id DESC
""",
    ),
    'sampling-signoff': (
        '抽检签核依据',
        '按批次核对托盘抽检结论、加权 C 级占比区间与签核快照，用于放行复核。',
        ['批次', '方案状态', '托盘数', '已判件数', 'C 级件数', '加权估计', '区间下限', '区间上限', '签核人', '签核时间'],
        """
SELECT l.code AS lot_code,p.state AS plan_state,
       (SELECT count(*) FROM sample_pallet sp WHERE sp.plan_id=p.id) AS pallets,
       p.basis->>'total_judged' AS judged,p.basis->>'total_c' AS c,
       p.basis->>'estimate' AS estimate,p.basis->>'low' AS low,p.basis->>'high' AS high,
       COALESCE(p.signed_by,'—') AS signer,COALESCE(to_char(p.signed_at,'MM-DD HH24:MI'),'—') AS signed_at
FROM sample_plan p JOIN pack_lot l ON l.id=p.lot_id ORDER BY p.id DESC
""",
    ),
}
