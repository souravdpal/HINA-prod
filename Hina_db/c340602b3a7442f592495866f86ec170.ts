import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

export function middleware(request: NextRequest) {
  const url = request.nextUrl;
  
  // Extract tracking information from incoming visitor routes
  const aff = url.searchParams.get('aff');
  const utmSource = url.searchParams.get('utm_source');
  const utmMedium = url.searchParams.get('utm_medium');
  const utmCampaign = url.searchParams.get('utm_campaign');

  const response = NextResponse.next();

  // If tracking tokens are present, burn them into secure cookies
  if (aff) {
    response.cookies.set('aff_token', aff, {
      maxAge: 60 * 60 * 24 * 30, // 30 Days Cookie
      path: '/',
      httpOnly: true,
      sameSite: 'lax',
    });
  }

  // Preserve UTM state across pages for attribution logic
  if (utmSource) {
    response.cookies.set('utm_source', utmSource, { maxAge: 60 * 60 * 24, path: '/' });
  }
  if (utmMedium) {
    response.cookies.set('utm_medium', utmMedium, { maxAge: 60 * 60 * 24, path: '/' });
  }
  if (utmCampaign) {
    response.cookies.set('utm_campaign', utmCampaign, { maxAge: 60 * 60 * 24, path: '/' });
  }

  return response;
}

export const config = {
  matcher: ['/', '/products/:path*'],
};
