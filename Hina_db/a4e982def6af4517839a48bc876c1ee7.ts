import { NextRequest, NextResponse } from 'next/server';
import { db } from '@/lib/db';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { clickToken, amount, externalTxId } = body;

    // Guard constraints
    if (!clickToken || typeof amount !== 'number') {
      return NextResponse.json({ error: 'Incomplete parameters supplied: clickToken and amount required' }, { status: 400 });
    }

    // Check header signature token to authorize execution safely
    const authHeader = request.headers.get('X-Affiliate-Auth');
    if (!authHeader) {
      return NextResponse.json({ error: 'Auth credentials signature verification failed' }, { status: 401 });
    }

    const affiliate = await db.affiliate.findUnique({
      where: { token: authHeader }
    });

    if (!affiliate || affiliate.status !== 'ACTIVE') {
      return NextResponse.json({ error: 'Access denied: Active credentials expected' }, { status: 403 });
    }

    // Lookup original click registry tracking entry
    const originatingClick = await db.click.findUnique({
      where: { clickToken },
      include: { product: true }
    });

    if (!originatingClick) {
      return NextResponse.json({ error: 'Valid matching source click token record was not found' }, { status: 404 });
    }

    // Calculate commission based on target product attributes
    const targetCommissionPct = originatingClick.product.commissionRate;
    const computedPayout = (amount * targetCommissionPct) / 100;

    // Record conversion to absolute database state ledger
    const conversion = await db.conversion.create({
      data: {
        clickToken,
        affiliateId: originatingClick.affiliateId,
        amount,
        commission: parseFloat(computedPayout.toFixed(2)),
        externalTxId,
        status: "APPROVED" // Programmatically set to approved for simulation purposes
      }
    });

    return NextResponse.json({
      success: true,
      transactionRegistered: conversion.id,
      payoutDistributed: computedPayout
    }, { status: 201 });

  } catch (error: any) {
    return NextResponse.json({ error: 'Platform runtime parse failure', details: error.message }, { status: 500 });
  }
}
