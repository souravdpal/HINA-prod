import React from 'react';
import Link from 'next/link';
import { db } from '@/lib/db';
import { ShoppingBag, ArrowUpRight, DollarSign, ExternalLink, Zap } from 'lucide-react';

// Seeding standard high-converting products directly inside the page render for zero-config startup
async function getProducts() {
  let products = await db.product.findMany();
  
  if (products.length === 0) {
    const seedData = [
      {
        title: "ApexCloud Super Cluster Server",
        slug: "apexcloud-super-cluster",
        description: "Scale high-frequency database architectures with bare-metal raw instances running isolated on custom PCIe fabrics.",
        price: 299.00,
        commissionRate: 20.0,
        targetUrl: "https://example.com/checkout/apexcloud",
        imageUrl: "https://images.unsplash.com/photo-1558494949-ef010cbdcc31?auto=format&fit=crop&w=400&q=80",
        category: "Cloud Infrastructure"
      },
      {
        title: "AI Matrix Processing Core Engine",
        slug: "ai-matrix-processing-engine",
        description: "Plug-and-play neural pipeline orchestrator designed to parallelize dense training sessions across massive nodes safely.",
        price: 1500.00,
        commissionRate: 15.0,
        targetUrl: "https://example.com/checkout/ai-matrix",
        imageUrl: "https://images.unsplash.com/photo-1620712943543-bcc4688e7485?auto=format&fit=crop&w=400&q=80",
        category: "Artificial Intelligence"
      },
      {
        title: "Quantum VPN Zero-Knowledge Protocol",
        slug: "quantum-vpn-zero-knowledge",
        description: "Encrypted lattice cryptosystem providing wireguard-grade protection, immune to mathematical post-quantum decryption vectors.",
        price: 89.00,
        commissionRate: 40.0,
        targetUrl: "https://example.com/checkout/quantum-vpn",
        imageUrl: "https://images.unsplash.com/photo-1563986768609-322da13575f3?auto=format&fit=crop&w=400&q=80",
        category: "Security"
      }
    ];

    for (const item of seedData) {
      await db.product.create({ data: item });
    }
    products = await db.product.findMany();
  }
  return products;
}

// Generate a mock Affiliate account to allow local testing out of the box
async function getOrCreateMockAffiliate() {
  let affiliate = await db.affiliate.findFirst();
  if (!affiliate) {
    affiliate = await db.affiliate.create({
      data: {
        name: "Supreme Partner Group",
        email: "partners@supreme.net",
        token: "partner_supreme_token_x909"
      }
    });
  }
  return affiliate;
}

export default async function HomePage() {
  const products = await getProducts();
  const mockAffiliate = await getOrCreateMockAffiliate();

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
      {/* Hero Section */}
      <div className="text-center max-w-4xl mx-auto mb-16">
        <span className="text-xs font-bold uppercase tracking-widest text-brand-500 bg-brand-500/10 px-4 py-1.5 rounded-full inline-block mb-4">
          Uncompromised Conversion Infrastructure
        </span>
        <h1 className="text-5xl md:text-7xl font-extrabold text-white tracking-tight leading-none mb-6">
          High-Ticket Affiliate <br />
          <span className="gradient-text">Attribution Architecture</span>
        </h1>
        <p className="text-gray-400 text-lg md:text-xl max-w-2xl mx-auto">
          Distribute products with millimeter-precise cookieless click redirection, resilient webhooks, and sub-second commission calculations.
        </p>
        <div className="mt-8 flex justify-center gap-4">
          <Link href="/dashboard" className="px-6 py-3 bg-brand-600 hover:bg-brand-700 font-semibold rounded-lg text-white transition flex items-center gap-2">
            View Analytics Console <ArrowUpRight size={18} />
          </Link>
          <a href="#marketplace" className="px-6 py-3 bg-dark-800 hover:bg-dark-100 hover:text-dark-900 border border-white/5 font-semibold rounded-lg text-gray-300 transition">
            Explore Offers
          </a>
        </div>
      </div>

      {/* Feature Badges */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-16">
        <div className="card-blur p-6 rounded-2xl">
          <div className="p-3 bg-brand-500/10 w-fit rounded-lg text-brand-500 mb-4">
            <Zap size={24} />
          </div>
          <h3 className="text-lg font-bold mb-2">Zero-Latency Tracker</h3>
          <p className="text-sm text-gray-400">
            Redirections process in under 12ms inside edge runtimes, tracking UTM components, location context, and system metadata.
          </p>
        </div>
        <div className="card-blur p-6 rounded-2xl">
          <div className="p-3 bg-brand-500/10 w-fit rounded-lg text-brand-500 mb-4">
            <DollarSign size={24} />
          </div>
          <h3 className="text-lg font-bold mb-2">Precise Ledger</h3>
          <p className="text-sm text-gray-400">
            Every dollar processed is tied instantly to originating click signatures, entirely neutralizing duplicate payouts.
          </p>
        </div>
        <div className="card-blur p-6 rounded-2xl">
          <div className="p-3 bg-brand-500/10 w-fit rounded-lg text-brand-500 mb-4">
            <ShoppingBag size={24} />
          </div>
          <h3 className="text-lg font-bold mb-2">Robust Commission Logic</h3>
          <p className="text-sm text-gray-400">
            Dynamic, flat, and tiered payout configurations adaptable with custom affiliate groups and platform overrides.
          </p>
        </div>
      </div>

      {/* Active Marketplace Section */}
      <div id="marketplace" className="scroll-mt-24">
        <div className="flex flex-col md:flex-row justify-between items-start md:items-end mb-8 gap-4">
          <div>
            <h2 className="text-2xl md:text-3xl font-extrabold text-white flex items-center gap-2">
              <ShoppingBag className="text-brand-500" /> Premium Campaigns
            </h2>
            <p className="text-sm text-gray-400 mt-1">
              Select verified high-converting assets below to extract secure, attribution-ready outbound links.
            </p>
          </div>
          <div className="bg-dark-800 border border-white/5 rounded-xl px-4 py-2 text-xs flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-brand-500 inline-block animate-ping"></span>
            <span className="text-gray-300 font-mono">Affiliate Context: {mockAffiliate.name}</span>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {products.map((product) => {
            // Generate standard dynamic routing affiliate tracker link
            const affiliateLink = `/api/clicks?product_id=${product.id}&aff_id=${mockAffiliate.id}&utm_source=apex_landing_page`;

            return (
              <div key={product.id} className="card-blur rounded-2xl overflow-hidden flex flex-col justify-between group hover:border-brand-500/40 transition duration-300">
                <div>
                  <div className="relative h-48 w-full overflow-hidden bg-dark-900">
                    <img
                      src={product.imageUrl}
                      alt={product.title}
                      className="object-cover w-full h-full opacity-80 group-hover:opacity-100 group-hover:scale-105 transition duration-500"
                    />
                    <div className="absolute top-3 right-3 bg-brand-600 text-white text-xs font-bold px-3 py-1.5 rounded-full">
                      {product.commissionRate}% Commission
                    </div>
                  </div>
                  <div className="p-6">
                    <span className="text-xs font-semibold text-brand-500 uppercase tracking-wider block mb-1">
                      {product.category}
                    </span>
                    <h3 className="text-lg font-bold text-white mb-2 leading-snug group-hover:text-brand-500 transition-colors">
                      {product.title}
                    </h3>
                    <p className="text-gray-400 text-sm leading-relaxed mb-4 line-clamp-3">
                      {product.description}
                    </p>
                  </div>
                </div>

                <div className="p-6 pt-0 mt-auto">
                  <div className="border-t border-dark-100/10 pt-4 mb-4 flex justify-between items-center">
                    <div>
                      <span className="text-xs text-gray-500 block">RETAIL VALUE</span>
                      <span className="text-lg font-bold text-white">${product.price.toFixed(2)}</span>
                    </div>
                    <div className="text-right">
                      <span className="text-xs text-gray-500 block">EST. PAYOUT</span>
                      <span className="text-lg font-bold text-brand-500">
                        ${((product.price * product.commissionRate) / 100).toFixed(2)}
                      </span>
                    </div>
                  </div>

                  <div className="space-y-2">
                    <a
                      href={affiliateLink}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="w-full text-center px-4 py-2.5 bg-brand-600 hover:bg-brand-700 text-white font-semibold text-sm rounded-lg transition duration-200 flex items-center justify-center gap-1.5"
                    >
                      Test Redirect Flow <ExternalLink size={14} />
                    </a>
                    <div className="bg-dark-900/90 rounded p-2 select-all font-mono text-[10px] text-gray-400 border border-white/5 truncate">
                      {`http://localhost:3000${affiliateLink}`}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
