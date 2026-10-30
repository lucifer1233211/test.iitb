import type { Metadata, Viewport } from 'next'
import { Inter, JetBrains_Mono } from 'next/font/google'
import './globals.css'
import { Providers } from '@/components/providers'
import { Toaster } from '@/components/ui/toaster'

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-sans',
  display: 'swap',
})

const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-mono',
  display: 'swap',
})

export const metadata: Metadata = {
  title: {
    default: 'IIT Bombay Security System',
    template: '%s | IIT Bombay Security',
  },
  description: 'Advanced facial recognition system for IIT Bombay campus security using CCTV and drone footage',
  keywords: [
    'facial recognition',
    'campus security',
    'CCTV monitoring',
    'drone surveillance',
    'IIT Bombay',
    'AI security system',
  ],
  authors: [
    {
      name: 'IIT Bombay Security Team',
    },
  ],
  creator: 'IIT Bombay Security System',
  openGraph: {
    type: 'website',
    locale: 'en_IN',
    url: 'https://security.iitb.ac.in',
    title: 'IIT Bombay Security System',
    description: 'Advanced facial recognition system for IIT Bombay campus security',
    siteName: 'IIT Bombay Security System',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'IIT Bombay Security System',
    description: 'Advanced facial recognition system for IIT Bombay campus security',
    creator: '@iaborofficial',
  },
  robots: {
    index: false,
    follow: false,
    googleBot: {
      index: false,
      follow: false,
    },
  },
}

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  maximumScale: 1,
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" suppressHydrationWarning data-scroll-behavior="smooth">
      <head>
        <link rel="icon" href="/favicon.png" type="image/png" />
        <link rel="apple-touch-icon" href="/iitb-logo.png" />
        <meta name="theme-color" content="#0ea5e9" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="default" />
        <meta name="apple-mobile-web-app-title" content="IITB Security" />
        <meta name="mobile-web-app-capable" content="yes" />
        <meta name="msapplication-TileColor" content="#0ea5e9" />
        <meta name="msapplication-tap-highlight" content="no" />
        
        <meta httpEquiv="X-Content-Type-Options" content="nosniff" />
      </head>
      <body
        className={`${inter.variable} ${jetbrainsMono.variable} font-sans antialiased min-h-screen bg-background`}
        suppressHydrationWarning
      >
        <Providers>
          <div className="relative flex min-h-screen flex-col">
            <div className="flex-1">
              {children}
            </div>
          </div>
          <Toaster />
        </Providers>
      </body>
    </html>
  )
}