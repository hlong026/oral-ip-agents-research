const cards = [
  {
    label: "套餐管理",
    value: "SKU / 版本",
    desc: "草稿、发布、下架和激活码绑定",
  },
  {
    label: "积分价格",
    value: "模块计费",
    desc: "统一价格目录，用户端只显示公开积分",
  },
  { label: "激活码", value: "一次性导出", desc: "批次、渠道、状态和兑换追踪" },
  {
    label: "Provider",
    value: "管理员承担",
    desc: "密钥、模型、健康状态由管理端维护",
  },
];

export default function OverviewPage() {
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">运营总览</h1>
        <p className="mt-2 text-sm text-text-3">
          第一版聚焦控制面：套餐、价格、激活码和供应商配置。
        </p>
      </div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {cards.map((card) => (
          <section key={card.label} className="glass p-5">
            <p className="text-sm text-text-3">{card.label}</p>
            <p className="mt-3 text-xl font-semibold">{card.value}</p>
            <p className="mt-2 text-sm text-text-3">{card.desc}</p>
          </section>
        ))}
      </div>
      <section className="glass p-5">
        <h2 className="font-medium">上线前检查</h2>
        <ul className="mt-3 grid gap-2 text-sm text-text-2 md:grid-cols-2">
          <li>普通用户不能访问 `/api/admin/v1/*`。</li>
          <li>激活码批次只能绑定已发布 SKU 版本。</li>
          <li>用户端只展示公开 SKU 和公开积分价格。</li>
          <li>Provider 密钥只在管理端配置，不进入用户端构建产物。</li>
        </ul>
      </section>
    </div>
  );
}
