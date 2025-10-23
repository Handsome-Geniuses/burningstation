import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Toaster } from "sonner";

export const metadata: Metadata = {
    title: "Burning Station!",
    description: "AHHHHHHHH",
}

export default function RootLayout({
    children,
}: Readonly<{
    children: React.ReactNode;
}>) {
    return (
        <html lang="en">
            <head>
                {/* <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1, user-scalable=no, interactive-widget=resizes-content"></meta> */}
                <link rel="preload" as="image" href="/meter.avif" />
                <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1, user-scalable=no, interactive-widget=resizes-content"></meta>
            </head>
            <body
                className={`antialiased overflow-hidden relative`}
            >
                {children}
                <Toaster position="bottom-left" className="" expand={true}/>
            </body>
        </html>
    );

}

