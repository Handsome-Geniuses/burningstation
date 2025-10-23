'use client'
import React from "react"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useStoreContext } from "@/app/dashboard/store"

const tlistcss = `
    h-9
    m-0 mt-[0.3rem] p-0 space-y-0 space-x-0 w-full px-3 relative bg-secondary
    before:content-[''] before:absolute before:left-0 
    before:-top-[0.3rem] before:h-[calc(0.3rem+1px)] before:w-full before:bg-primary 
    before:rounded-b-md
`
const sidebordermaybe = `
    before:content-[''] before:absolute
    before:top-1/2 before:-translate-y-1/2
    before:h-[50%] before:w-full before:z-[3]
    before:border-t-0 before:border-b-0
    before:border-l before:border-r before:border-foreground/50
    data-[state=active]:before:border-0
`

const TTrigger = (props: React.ComponentPropsWithoutRef<typeof TabsTrigger>) => {
    return (
        <TabsTrigger
            {...props}
            className={`
                ${props.className} bg-secondary text-foreground
                data-[state=active]:bg-primary data-[state=active]:z-1 data-[state=active]:text-secondary
                space-x-0 space-y-0 m-0 rounded-t-none border-0
                hover:bg-primary/33 hover:z-3

                group relative
                
            `}
        >
            {props.children}
            <div className="pointer-events-none absolute -left-2 top-0 w-[calc(100%+1rem)] h-2 z-1 bg-primary opacity-0 group-data-[state=active]:opacity-100 " />
            <div className="pointer-events-none absolute right-[100%] top-0 bg-secondary w-2 h-2 z-1 opacity-0 group-data-[state=active]:opacity-100 rounded-tr-md" />
            <div className="pointer-events-none absolute left-[100%] top-0 bg-secondary w-2 h-2 z-1 opacity-0 group-data-[state=active]:opacity-100 rounded-tl-md" />
        </TabsTrigger>
    )
}

const TContent = (props: React.ComponentPropsWithoutRef<typeof TabsContent>) => {
    return (
        <TabsContent {...props} />
    )
}

export interface TabItem {
    value: string
    label?: string
    content: React.ReactNode
}
export interface TabinationProps {
    defaultValue?: string
    tabs: TabItem[]
}

export const Tabination = ({ tabs, ...props }: TabinationProps & React.ComponentPropsWithoutRef<typeof Tabs>) => {
    const { systemState, systemDispatch } = useStoreContext()
    const defaultValue = tabs[0].value

    const changeTab=(value:string)=>{
        systemDispatch({ type: 'set', key: 'currentTab', value: value })
    }
    React.useEffect(()=>{
        if (systemState.currentTab==undefined) changeTab(tabs[0].value)
    },[systemState.currentTab])

    return (
        <Tabs
            value={systemState.currentTab ?? defaultValue}
            onValueChange={changeTab}
            className="h-full w-full gap-0"
            {...props}
        >
            {tabs.map((tab) => (
                <TContent key={tab.value} value={tab.value}>
                    <div className="w-full h-full relative flex flex-col [&>*]:flex-1">
                        {tab.content}
                    </div>
                </TContent>
            ))}
            <TabsList className={tlistcss}>
                {tabs.map((tab, i) => (
                    <TTrigger key={tab.value} value={tab.value}>{tab.label ?? tab.value}</TTrigger>
                ))}
            </TabsList>
        </Tabs>
    )
}
