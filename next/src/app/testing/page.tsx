'use client'
import { Slider } from "@/components/ui/slider"
import React from "react"


export default () => {
    const [value, setValue] = React.useState(50)
    const [value1, setValue1] = React.useState(50)
    return (
        <div className="space-y-4 m-4">
            hello
            <Slider
                className="h-20 w-100 !rounded"
                value={value}
                onValueChange={(setValue)}
                min={0}
                max={100}
                thumb={"bar"}
            />


            <Slider
                className="h-10 w-100 !rounded-full"
                value={value1}
                onValueChange={(setValue1)}
                min={0}
                max={100}
                thumb={"ball"}
            />
        </div>
    )
}


