'use client'
import { flask } from "@/lib/flask"
import React from "react"


const Layout1 = ()=>{
    return (
        <div className="relative w-full h-full bg-blue-100">
            <header className="h-16 bg-green-100">

            </header>
        </div>
    )
}

export default () => {
    const [loading, setLoading] = React.useState(false)
    return (
        <div className="border border-[#ff0000] border-1 w-[1920px] h-[1080px] z-999999 overflow-hidden ">
            {/* hello */}
            <Layout1 />
        </div>
    )
}