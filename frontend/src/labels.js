export const STATES = {new:'待采样', blocked:'通道缺失', measured:'待判级', queued:'计算中', review:'待签核', rework:'返工中', approved:'待关闭', closed:'已关闭', requested:'待领料', issued:'待复测', verified:'已复测', open:'待复核', confirmed:'已确认', dismissed:'已驳回', predicted:'待签核', signed:'已签核', failed:'可重试', sampling:'抽检中', ready:'待签核', full_inspection:'全检中', rejected:'已判退', pass:'结论合格', fail:'结论超阈', pending:'待判级', judged:'已判级', sample:'抽检', full:'全检'};
export const ROLES = {operator:'线边操作员', supervisor:'质检主管', viewer:'排产查看'};
export const GRADES = {A:'外观合格', B:'外观待修', C:'严重偏差'};
export const MACHINES = ['VS-01','VS-02','VS-03'];
export const CHANNELS = [
  ['wrinkle_pct','褶皱面积','%',100], ['offset_mm','印刷偏位','mm',20], ['delta_e','综合色差','ΔE',60],
  ['seal_gap_mm','封口间隙','mm',12], ['gloss_cv','光泽波动','%',100],
];
export const DEFECTS = {wrinkle:'褶皱', offset:'印刷偏位', color:'色差', seal:'热封异常', gloss:'光泽不均'};
export const ZONES = {front:'正面', back:'背面', 'top-seal':'上封口', 'bottom-seal':'下封口'};
export const EVENT_LABELS = {lot_registered:'包装批次登记', measurement_saved:'测量版本归档', channels_missing:'通道缺失，禁止判级', defect_marked:'记录缺陷位置', defect_reviewed:'签核缺陷标记', grade_queued:'提交模型判级', model_predicted:'模型建议已回写', grade_failed:'判级计算失败', grade_signed:'主管签核等级', rework_requested:'生成返工领料单', material_issued:'膜材领料过账', rework_retest_rejected:'返工复测未通过', rework_verified:'返工复测通过', lot_closed:'关闭包装批次', plan_created:'抽检方案登记', round_issued:'抽次件号发放', pallet_concluded:'托盘结论达成', pallet_full_inspection:'托盘转全检', plan_ready:'抽检达标待签核', plan_full_inspection:'批次转全检', plan_rejected:'抽检判退', plan_signed:'抽检签核放行'};
