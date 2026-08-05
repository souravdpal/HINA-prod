export interface Metrics {
  clicksCount: number;
  conversionsCount: number;
  conversionRate: number;
  totalSales: number;
  totalCommission: number;
  epc: number; // Earnings Per Click
}

export function calculateMetrics(clicksCount: number, conversions: { amount: number; commission: number }[]): Metrics {
  const conversionsCount = conversions.length;
  const conversionRate = clicksCount > 0 ? (conversionsCount / clicksCount) * 100 : 0;
  const totalSales = conversions.reduce((sum, c) => sum + c.amount, 0);
  const totalCommission = conversions.reduce((sum, c) => sum + c.commission, 0);
  const epc = clicksCount > 0 ? totalCommission / clicksCount : 0;

  return {
    clicksCount,
    conversionsCount,
    conversionRate: parseFloat(conversionRate.toFixed(2)),
    totalSales: parseFloat(totalSales.toFixed(2)),
    totalCommission: parseFloat(totalCommission.toFixed(2)),
    epc: parseFloat(epc.toFixed(2)),
  };
}
