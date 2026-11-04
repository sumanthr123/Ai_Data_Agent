import { Area, AreaChart, ResponsiveContainer } from 'recharts'

export function Sparkline({ values, id }: { values: number[]; id: string }) {
  const data = values.map((v, i) => ({ i, v }))
  return (
    <ResponsiveContainer width="100%" height={36}>
      <AreaChart data={data} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id={`spark-${id}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#22d3ee" stopOpacity={0.45} />
            <stop offset="100%" stopColor="#22d3ee" stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area type="monotone" dataKey="v" stroke="#22d3ee" strokeWidth={1.5} fill={`url(#spark-${id})`} isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  )
}
