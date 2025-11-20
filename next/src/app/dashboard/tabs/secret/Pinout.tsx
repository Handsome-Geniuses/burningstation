"use client";
import {
    Dialog,
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
} from "@/components/ui/dialog"
import { flask } from "@/lib/flask";
import { Key } from "lucide-react";
import React from "react";
export const Pinout = () => {
    const [pinout, setPinout] = React.useState<null | {}>(null)

    const getPinout = async () => {
        if (pinout == null) {
            const res = await flask.get("/hardware")
            const data = await res.json()
            console.log(data)
            setPinout(data)
        }
    }
    React.useEffect(() => { getPinout() }, [])

    return (
        <Dialog>
            <DialogTrigger asChild>
                {/* <Button variant="outline">?</Button> */}
                <div className="cursor-pointer absolute top-0 right-0 m-1 w-6 h-6 rounded-full bg-border flex items-center justify-center">
                    ?
                </div>
            </DialogTrigger>
            <DialogContent className="">
                <DialogHeader className="">
                    <DialogTitle>Hardware Wiring</DialogTitle>
                    <DialogDescription className="h-0 w-0 hidden" />
                </DialogHeader>
                <div>
                    {/* {JSON.stringify(pinout,null,"\t")} */}
                    {
                        pinout && Object.entries(pinout).map(([key, value]) => (
                            <div key={key} className="flex gap-2 whitespace-pre font-mono">
                                <div>{(key.toString().trim()).padEnd(13," ")} </div>
                                <div>: </div>
                                <div>{JSON.stringify(value)}</div>
                            </div>
                        ))
                    }
                </div>
            </DialogContent>
        </Dialog>
    )
}