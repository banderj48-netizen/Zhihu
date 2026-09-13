import './globals.css';
import type { Metadata } from 'next';
export const metadata: Metadata = { title: '知交桥 · 让认识发生在生活里', description: '知识社区轻社交演示站' };
export default function RootLayout({children}:{children:React.ReactNode}) { return <html lang="zh-CN"><body>{children}</body></html> }
