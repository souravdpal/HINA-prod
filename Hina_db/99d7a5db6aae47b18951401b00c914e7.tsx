import React from 'react';
import { db } from '@/lib/db';
import { calculateMetrics } from '@/lib/analytics';
import { 
  TrendingUp, 
  MousePointerClick, 
  RefreshCw, 
  DollarSign, 
  Percent, 
  BarChart4, 
  Calendar, 
  UserPlus
} from 'lucide-react';

async function getDashboardData() {
  const affiliate = await db.affiliate.findFirst();
  if (!affiliate) {
    return null;
  }

  // Gather stats
  const totalClicks = await db.click.count({
    where: { affiliateId: affiliate.id }
  });

  const conversions = await db.conversion.findMany({
    where: { 
      affiliateId: affiliate.id,
      status: "APPROVED" 
    },
    select: {
      amount: true,
      commission: true
    }
  });

  const recentConversions = await db.conversion.findMany({
    where: { affiliateId: affiliate.id },
    orderBy: { createdAt: 'desc' },
    take: 5,
    include: {
      click: {
        include: { product: true }
      }
    }
  });

  const recentClicks = await db.click.findMany({
    where: { affiliateId: affiliate.id },
    orderBy: { createdAt: 'desc' },
    take: 5,
    include: {
      product: true
    }
  });

  const metrics = calculateMetrics(totalClicks, conversions);

  return {
    affiliate,
    metrics,
    recentConversions,
    recentClicks
  };
}

export default async function DashboardPage() {
  const data = await getDashboardData();

  if (!data) {
    return (
      <div className="max-w-7xl mx-auto px-4 py-16 text-center">
        <h2 className="text-xl font-bold">No active affiliate token found.</h2>
        <p className="text-gray-400">Please seed database by visiting home page first.</p>
      </div>
    );
  }

  const { affiliate, metrics, recentConversions, recentClicks } = data;

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
      
      {/* Dashboard Header */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-10 pb-6 border-b border-dark-100/10">
        <div>
          <h1 className="text-3xl font-extrabold text-white">Affiliate Console</h1>
          <p className="text-gray-400 text-sm mt-1">
            Realtime campaign performance for <span className="text-brand-500 font-semibold">{affiliate.name}</span>
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="bg-dark-800 text-gray-300 rounded-lg px-4 py-2 border border-white/5 text-xs">
            <span className="text-gray-500 mr-2">Token:</span>
            <span className="font-mono text-brand-500 font-bold select-all">{affiliate.token}</span>
          </div>
          <button className="bg-brand-600 hover:bg-brand-700 text-white rounded-lg p-2.5 transition">
            <RefreshCw size={16} />
          </button>
        </div>
      </div>

      {/* KPI Metrics Dashboard Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 mb-10">
        
        {/* KPI: Clicks */}
        <div className="card-blur p-6 rounded-2xl relative overflow-hidden">
          <div className="flex justify-between items-start">
            <div>
              <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider block mb-1">
                Total Traffic Clicks
              </span>
              <span className="text-3xl font-black text-white">{metrics.clicksCount}</span>
            </div>
            <div className="p-2.5 bg-blue-500/10 rounded-xl text-blue-400">
              <MousePointerClick size={22} />
            </div>
          </div>
          <div className="mt-4 flex items-center text-xs text-blue-400 font-semibold">
            <TrendingUp size={14} className="mr-1" />
            <span>Realtime tracking active</span>
          </div>
        </div>

        {/* KPI: Conversion Rate */}
        <div className="card-blur p-6 rounded-2xl relative overflow-hidden">
          <div className="flex justify-between items-start">
            <div>
              <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider block mb-1">
                Conversion Rate
              </span>
              <span className="text-3xl font-black text-white">{metrics.conversionRate}%</span>
            </div>
            <div className="p-2.5 bg-yellow-500/10 rounded-xl text-yellow-400">
              <Percent size={22} />
            </div>
          </div>
          <div className="mt-4 flex items-center text-xs text-yellow-400 font-semibold">
            <TrendingUp size={14} className="mr-1" />
            <span>Across all offers</span>
          </div>
        </div>

        {/* KPI: Earnings Per Click (EPC) */}
        <div className="card-blur p-6 rounded-2xl relative overflow-hidden">
          <div className="flex justify-between items-start">
            <div>
              <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider block mb-1">
                EPC (Earnings Per Click)
              </span>
              <span className="text-3xl font-black text-white">${metrics.epc}</span>
            </div>
            <div className="p-2.5 bg-purple-500/10 rounded-xl text-purple-400">
              <BarChart4 size={22} />
            </div>
          </div>
          <div className="mt-4 flex items-center text-xs text-purple-400 font-semibold">
            <TrendingUp size={14} className="mr-1" />
            <span>Optimal traffic value</span>
          </div>
        </div>

        {/* KPI: Total Commission */}
        <div className="card-blur p-6 rounded-2xl relative overflow-hidden border-brand-500/20">
          <div className="flex justify-between items-start">
            <div>
              <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider block mb-1">
                Total Commission Payout
              </span>
              <span className="text-3xl font-black text-brand-500">${metrics.totalCommission}</span>
            </div>
            <div className="p-2.5 bg-brand-500/10 rounded-xl text-brand-500">
              <DollarSign size={22} />
            </div>
          </div>
          <div className="mt-4 flex items-center text-xs text-brand-500 font-semibold">
            <TrendingUp size={14} className="mr-1" />
            <span>Available for withdrawal</span>
          </div>
        </div>

      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        
        {/* Recent Commissions Ledger */}
        <div className="card-blur rounded-2xl p-6">
          <div className="flex justify-between items-center mb-6">
            <h3 className="text-lg font-bold text-white flex items-center gap-2">
              <DollarSign size={18} className="text-brand-500" /> Commission Ledger
            </h3>
            <span className="text-xs bg-brand-500/10 text-brand-500 font-semibold px-2.5 py-1 rounded">
              Conversions
            </span>
          </div>

          {recentConversions.length === 0 ? (
            <div className="h-64 flex flex-col items-center justify-center text-center border-2 border-dashed border-dark-100/10 rounded-xl">
              <p className="text-gray-500 text-sm">No recorded payouts found yet.</p>
              <p className="text-xs text-gray-600 mt-1">Fire conversions via the postback endpoint.</p>
            </div>
          ) : (
            <div className="space-y-4">
              {recentConversions.map((conv) => (
                <div key={conv.id} className="bg-dark-950 p-4 rounded-xl flex justify-between items-center border border-white/[0.02]">
                  <div>
                    <span className="text-xs text-gray-400 block font-mono">ID: {conv.id.substring(0, 8)}...</span>
                    <span className="text-sm font-semibold text-white mt-1 block">
                      {conv.click.product.title}
                    </span>
                    <span className="text-[10px] text-gray-500 block mt-0.5">
                      {new Date(conv.createdAt).toLocaleString()}
                    </span>
                  </div>
                  <div className="text-right">
                    <span className="text-sm font-black text-brand-500 block">+${conv.commission.toFixed(2)}</span>
                    <span className={`text-[10px] px-2 py-0.5 rounded font-bold uppercase inline-block mt-1 ${
                      conv.status === 'APPROVED' ? 'bg-brand-500/10 text-brand-500' : 'bg-yellow-500/10 text-yellow-500'
                    }`}>
                      {conv.status}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Realtime Click Pipeline */}
        <div className="card-blur rounded-2xl p-6">
          <div className="flex justify-between items-center mb-6">
            <h3 className="text-lg font-bold text-white flex items-center gap-2">
              <MousePointerClick size={18} className="text-blue-500" /> Redirect Clickstream
            </h3>
            <span className="text-xs bg-blue-500/10 text-blue-400 font-semibold px-2.5 py-1 rounded">
              Live Stream
            </span>
          </div>

          {recentClicks.length === 0 ? (
            <div className="h-64 flex flex-col items-center justify-center text-center border-2 border-dashed border-dark-100/10 rounded-xl">
              <p className="text-gray-500 text-sm">No incoming clicks captured yet.</p>
              <p className="text-xs text-gray-600 mt-1">Visit dynamic offers to populate traffic logs.</p>
            </div>
          ) : (
            <div className="space-y-4">
              {recentClicks.map((click) => (
                <div key={click.id} className="bg-dark-950 p-4 rounded-xl flex justify-between items-center border border-white/[0.02]">
                  <div>
                    <span className="text-xs text-gray-400 block font-mono">Token: {click.clickToken.substring(0, 10)}...</span>
                    <span className="text-sm font-semibold text-white mt-1 block">
                      {click.product.title}
                    </span>
                    <div className="flex gap-2 mt-1">
                      {click.utmSource && (
                        <span className="text-[9px] bg-dark-800 text-gray-400 px-1.5 py-0.5 rounded border border-white/5 font-mono">
                          src: {click.utmSource}
                        </span>
                      )}
                      {click.ipAddress && (
                        <span className="text-[9px] bg-dark-800 text-gray-400 px-1.5 py-0.5 rounded border border-white/5 font-mono">
                          IP: {click.ipAddress}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="text-right">
                    <span className="text-xs text-gray-500 block">
                      {new Date(click.createdAt).toLocaleTimeString()}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

      </div>

      {/* Integration Docs / Hook Trigger Simulation */}
      <div className="card-blur rounded-2xl p-6 mt-10">
        <h3 className="text-lg font-bold text-white mb-2 flex items-center gap-2">
          <UserPlus size={18} className="text-yellow-500" /> Postback & Commission Simulation Loop
        </h3>
        <p className="text-sm text-gray-400 mb-6">
          To credit conversions securely from checkout platforms, route payment confirmation parameters into our webhooks system. Use the payload setup below for automatic ledger calculations.
        </p>

        <div className="bg-dark-950 rounded-xl p-4 border border-white/5 font-mono text-xs overflow-x-auto">
          <p className="text-brand-500 mb-2">// POST confirmation parameters to postback webhook</p>
          <p className="text-white font-bold mb-4">POST /api/webhooks/conversion</p>
          <span className="text-gray-400">Headers:</span>
          <pre className="text-yellow-400 mt-1 mb-4">{`Content-Type: "application/json"
X-Affiliate-Auth: "${affiliate.token}"`}</pre>
          <span className="text-gray-400">Payload:</span>
          <pre className="text-green-400 mt-1">{`{
  "clickToken": "${recentClicks[0]?.clickToken || 'SAMPLE_CLICK_TOKEN'}",
  "amount": 299.00,
  "externalTxId": "TX_${Math.floor(Math.random() * 9000000) + 1000000}"
}`}</pre>
        </div>
      </div>

    </div>
  );
}
