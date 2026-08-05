import './globals.css';
import React from 'react';
import Link from 'next/link';
import { Activity, ShieldCheck, ShoppingBag, LayoutDashboard } from 'lucide-react';

export const metadata = {
  title: 'ApexAffiliate - Hyper Scale Affiliate Engine',
  description: 'Ultra high-performance conversion, attribution and affiliate tracking ecosystem.',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen flex flex-col justify-between">
        <header className="border-b border-dark-100/10 bg-dark-950/80 sticky top-0 z-50 backdrop-blur-md">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
            <div className="flex items-center space-x-8">
              <Link href="/" className="flex items-center space-x-2">
                <div className="bg-brand-600 p-2 rounded-lg text-white">
                  <Activity size={20} className="animate-pulse" />
                </div>
                <span className="font-extrabold text-xl tracking-tight text-white">
                  APEX<span className="text-brand-500">AFFILIATE</span>
                </span>
              </Link>
              <nav className="hidden md:flex space-x-6 text-sm font-medium text-gray-300">
                <Link href="/" className="hover:text-brand-500 transition-colors flex items-center gap-1">
                  <ShoppingBag size={15} /> Marketplace
                </Link>
                <Link href="/dashboard" className="hover:text-brand-500 transition-colors flex items-center gap-1">
                  <LayoutDashboard size={15} /> Affiliate Dashboard
                </Link>
              </nav>
            </div>
            <div className="flex items-center space-x-4">
              <div className="hidden sm:flex items-center space-x-1 text-xs text-brand-500 bg-brand-500/10 px-3 py-1.5 rounded-full font-semibold">
                <ShieldCheck size={14} />
                <span>Live Attribution Engaged</span>
              </div>
            </div>
          </div>
        </header>

        <main className="flex-grow">{children}</main>

        <footer className="border-t border-dark-100/10 bg-dark-950 py-8 mt-12">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col md:flex-row justify-between items-center gap-4 text-sm text-gray-500">
            <div>
              &copy; {new Date().getFullYear()} ApexAffiliate Platform. All rights reserved.
            </div>
            <div className="flex space-x-6">
              <span className="text-gray-400 hover:text-white cursor-pointer transition">Developer API</span>
              <span className="text-gray-400 hover:text-white cursor-pointer transition">Attribution Policy</span>
              <span className="text-gray-400 hover:text-white cursor-pointer transition">Webhook Specs</span>
            </div>
          </div>
        </footer>
      </body>
    </html>
  );
}
