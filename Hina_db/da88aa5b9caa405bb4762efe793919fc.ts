import { NextRequest, NextResponse } from 'next/server';
import { db } from '@/lib/db';

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const productId = searchParams.get('product_id');
  const affiliateId = searchParams.get('aff_id');
  const utmSource = searchParams.get('utm_source') || undefined;
  const utmMedium = searchParams.get('utm_medium') || undefined;
  const utmCampaign = searchParams.get('utm_campaign') || undefined;

  if (!productId) {
    return NextResponse.json({ error: 'Required parameter: product_id is missing.' }, { status: 400 });
  }

  // Retrieve matching target product
  const product = await db.product.findUnique({
    where: { id: productId }
  });

  if (!product) {
    return NextResponse.json({ error: 'Requested campaign offer not found.' }, { status: 404 });
  }

  // Generated dynamic lookup click identification key
  const clickToken = `cl_${Math.random().toString(36).substring(2, 15)}_${Date.now().toString(36)}`;

  // Capture visitor environment metadata
  const ipAddress = request.headers.get('x-forwarded-for') || '127.0.0.1';
  const userAgent = request.headers.get('user-agent') || 'Unknown';
  const referrer = request.headers.get('referer') || undefined;

  // Track the event
  await db.click.create({
    data: {
      clickToken,
      productId,
      affiliateId,
      referrer,
      ipAddress,
      userAgent,
      utmSource,
      utmMedium,
      utmCampaign
    }
  });

  // Construct target destination adding the attribution click token back to payload params
  const destinationUrl = new URL(product.targetUrl);
  destinationUrl.searchParams.set('click_token', clickToken);
  if (affiliateId) {
    destinationUrl.searchParams.set('affiliate_id', affiliateId);
  }

  // Instantly redirect with cookies embedded for backup offline redundancy
  const response = NextResponse.redirect(destinationUrl.toString(), 302);
  response.cookies.set('apex_last_click', clickToken, {
    maxAge: 60 * 60 * 24 * 30, // 30 Days
    path: '/'
  });

  return response;
}
