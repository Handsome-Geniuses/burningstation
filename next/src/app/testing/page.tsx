'use client'
import React from "react"
import { Tabination, TabItem } from "@/components/ui/tabination"
const Layout1 = () => {
    return (
        <div className="relative w-full h-full bg-blue-100 flex flex-col bg-background">
            <div className="h-12 border border-red-500 border-1">header even needed?</div>
            <div className="grid grid-cols-[25%_50%_25%] flex-1">
                <div className="border border-red-500 border-1 p-2">statuses?</div>
                <div className="border border-red-500 border-1 p-2">visuals?</div>
                <div className="border border-red-500 border-1 p-2">controls</div>
            </div>
        </div>
    )
}
const Layout2 = ()=>{
    const tabs = Array.from({length:5}).map((_,i)=>({value:`page${i}`,label:`Page${i}`,content:<div>Content {i}</div>}))
    return (
        <Tabination defaultValue="page1" tabs={tabs}/>
    )
}
const Layout3 = ()=>{
    return (
        <div className="bg-teal-300">

        </div>
    )
}


export default () => {
    const [loading, setLoading] = React.useState(false)

    const tabs:TabItem[] = [
        {value:"def", label:"Layout 1", content:<Layout1/>},
        {value:"2", label:"Layout 2", content:<Layout1/>},
        {value:"3", label:"Layout 3", content:<Layout3/>}

    ]
    return (
        <div className="border border-[#ff0000] border-1 w-[1920px] h-[1080px] z-999999 overflow-hidden ">
            {/* hello */}
            {/* <Layout2 /> */}

            <Tabination tabs={tabs}/>
        </div>
    )
}




{/* <div className="w-screen h-screen bg-neutral-500 overflow-hidden flex justify-center items-center">
            <div className="bg-background relative w-[1920px] h-[1080px] flex flex-col">
                <StoreProvider>
                    <Dashboard />
                </StoreProvider>
            </div>
        </div> */}