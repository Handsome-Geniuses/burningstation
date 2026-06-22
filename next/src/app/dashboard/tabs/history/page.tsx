import { flask } from "@/lib/flask"
import { Button } from "@/components/ui/button"
import React from "react"
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
import { ScrollArea } from "@/components/ui/scroll-area";
import {
    Accordion,
    AccordionContent,
    AccordionItem,
    AccordionTrigger,
} from "@/components/ui/accordion"
import { LucideAlertTriangle, LucideCheck, LucideCopy, LucideShieldBan, LucideShieldQuestion, LucideX } from "lucide-react";
import { useStoreContext } from "../../store";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";

const retrieve_limit = 10;

const formatDate = (date: string | number | Date) =>
    new Date(date).toLocaleString("en-US", {
        month: "2-digit",
        day: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: true
    });

const retrieveJobHistoryPlaceholder = async (limit: number, offset: number) => {
    // Placeholder for fetching job history data
    return [
        { id: 1, status: 'Completed' },
        { id: 2, status: 'In Progress' },
        { id: 3, status: 'Failed' },
        { id: 4, status: 'Completed' },
        { id: 5, status: 'In Progress' },
        { id: 6, status: 'Failed' },
        { id: 7, status: 'Completed' },
        { id: 8, status: 'In Progress' },
        { id: 9, status: 'Failed' },
        { id: 10, status: 'Completed' },
    ]
}

const retrieveJobHistory = async (limit: number, offset: number) => {
    // const response = await fetch(`/api/database/meter_jobs?limit=${limit}&offset=${offset}`);
    const response = await flask.get(`/database/meter_job?limit=${limit}&offset=${offset}`)
    const data = await response.json()
    return data
}

const statusIcon = (status: string, className?: string) => {
    // switch (status) {
    //     case 'pass':
    //         return "✅"
    //     case 'fail':
    //         return "❌"
    //     case 'missing':
    //         return "⚠️"
    //     case 'n/a':
    //         return "❓"
    //     default:
    //         return "❔"
    // }
    switch (status) {
        case 'pass':
            return <LucideCheck className={cn("size-6 text-green-500 inline-block", className)} />
        case 'fail':
            return <LucideX className={cn("size-6 text-red-500 inline-block", className)} />
        case 'missing':
            return <LucideAlertTriangle className={cn("size-6 text-yellow-500 inline-block", className)} />
        case 'n/a':
            return <LucideShieldQuestion className={cn("size-6 text-gray-500 inline-block", className)} />
        default:
            return <LucideShieldBan className={cn("size-6 text-gray-500 inline-block", className)} />
    }
}


const JobRow = ({ job, onClick }: { job: any, onClick?: () => void }) => {
    const icon = statusIcon(job?.status)

    return (
        <tr onClick={onClick} className="border-b cursor-pointer hover:bg-gray-50">
            <td className="text-center">{icon}</td>
            <td className="text-left">{job.id}</td>
            <td className="text-left">{job.hostname}</td>
            <td className="text-left">{job.name}</td>
            {/* <td className="text-left">{new Date(job.created_at).toLocaleString()}</td> */}
            <td className="text-left">{job?.created_at.replace(" GMT", "")}</td>
        </tr>
    )
}
const Copyable = ({ text }: { text: string }) => {
    const copyToClipboard = () => {
        navigator.clipboard.writeText(text)
        notify.info('Copied to clipboard')
    }
    return <LucideCopy className="cursor-pointer ml-2" onClick={copyToClipboard} />
}

const copyme = (text: string) => {
    navigator.clipboard.writeText(text)
    notify.info('Copied to clipboard')
}

const JobDialog = ({ job, detailed = false }: { job: any, detailed?: boolean }) => {
    const { systemState, systemDispatch } = useStoreContext()
    const isHandsome = systemState.handsome
    const icon = statusIcon(job?.status)
    const results = job?.data?.results
    return (
        <>
            <DialogContent className="min-w-[85vw]">
                <DialogHeader className="gap-0 space-y-0 m-0 p-0 border-0">
                    <DialogTitle>Job Details — {job?.hostname} — {job?.name} — {job?.status}{icon}</DialogTitle>
                    <DialogDescription>
                        {job?.created_at}
                    </DialogDescription>
                </DialogHeader>

                <ScrollArea className={cn("mt-2 max-h-80 overflow-y-auto w-full rounded-md border-border px-2 mr-2", detailed ? "border" : "border-0")}>
                    {detailed
                        ? <Accordion type="single" collapsible>
                            {job?.data?.kwargs &&
                                <AccordionItem value="kwargs">
                                    <AccordionTrigger>program parameters(kwargs)</AccordionTrigger>
                                    <AccordionContent>
                                        {/* {isHandsome && <Copyable text={JSON.stringify(job?.data?.kwargs, null, 2)} />} */}
                                        <pre className="bg-gray-100 rounded-md cursor-default" onClick={() => isHandsome && copyme(JSON.stringify(job?.data?.kwargs, null, 2))}>
                                            {JSON.stringify(job?.data?.kwargs, null, 2)}
                                        </pre>
                                    </AccordionContent>
                                </AccordionItem>
                            }
                            {results &&
                                <AccordionItem value="results">
                                    <AccordionTrigger>results</AccordionTrigger>
                                    <AccordionContent>
                                        {/* {isHandsome && <Copyable text={JSON.stringify(job?.data?.results, null, 2)} />} */}
                                        <pre className="bg-gray-100 rounded-md p-2 cursor-default" onClick={() => isHandsome && copyme(JSON.stringify(job?.data?.results, null, 2))}>
                                            {JSON.stringify(results, null, 2)}
                                        </pre>
                                    </AccordionContent>
                                </AccordionItem>
                            }
                            {job?.jctl &&
                                <AccordionItem value="journalctl">
                                    <AccordionTrigger>journalctl</AccordionTrigger>
                                    <AccordionContent>
                                        {/* {isHandsome && <Copyable text={job?.jctl} />} */}
                                        <div className="bg-gray-100 rounded-md p-2  cursor-default" onClick={() => isHandsome && copyme(job?.jctl)}>
                                            {job?.jctl}
                                        </div>
                                    </AccordionContent>
                                </AccordionItem>
                            }
                        </Accordion>
                        : <div className="text-sm space-y-0.5">
                            <p className={cn("text-base", results && "border-b")}>
                                OVERALL -- {icon}
                            </p>
                            {results &&
                                Object.entries(results).map(([key, res]: [string, any]) => (
                                    <p key={key} className="flex items-center gap-1">
                                        {`${key} -- `} {statusIcon("pass", "size-5")}
                                    </p>
                                ))
                            }
                        </div>
                    }
                </ScrollArea>
                <DialogFooter >
                    <DialogClose asChild >
                        <Button variant="secondary">Close</Button>
                    </DialogClose>
                </DialogFooter>
            </DialogContent>
        </>
    )
}


export const HistoryTab = () => {
    const [jobs, setJobs] = React.useState<any[]>([])
    const [selected, setSelected] = React.useState<any>(null)
    const [dialogOpen, setDialogOpen] = React.useState(false)
    const [detailed, setDetailed] = React.useState(false)

    const fetchJobs = async () => {
        const offset = jobs.length
        const newJobs = await retrieveJobHistory(retrieve_limit, offset)
        setJobs([...jobs, ...newJobs])
    }

    const openJobDialog = (job: any) => {
        setSelected(job)
        setDialogOpen(true)
    }

    return (
        <div className="relative px-4 pb-4">
            {/* <div className="w-full max-w-2xl max-h-96 overflow-y-auto rounded-md bg-red-100 px-4"> */}
            <div className={cn(" m-1 ml-auto size-fit")}>
                <button
                    className={cn(
                        "rounded py-0.5 px-2 min-w-20 rounded size-fit active:translate-y-px border border-border",
                        detailed ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground",
                    )}
                    onClick={() => setDetailed(old => !old)}
                >
                    {detailed ? "detailed" : "simple"}
                </button>
            </div>
            <div className="w-full max-h-100 overflow-y-auto rounded-md border border-border">
                <table className="w-full table-auto border-collapse">
                    <thead className="bg-gray-100 sticky top-0">
                        <tr>
                            <th className="text-left"></th>
                            <th className="text-left">ID</th>
                            <th className="text-left">Meter</th>
                            <th className="text-left">Job</th>
                            <th className="text-left">Finished</th>
                        </tr>
                    </thead>
                    <tbody>
                        {jobs.map((job, i) => <JobRow key={`[${i}]${job.id}`} job={job} onClick={() => openJobDialog(job)} />)}
                    </tbody>
                </table>
                <div className="flex justify-center my-4">
                    <Button variant={"secondary"} onClick={fetchJobs} className="w-fit">load 10 more</Button>
                </div>
            </div>
            <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
                <JobDialog job={selected} detailed={detailed} />
            </Dialog>
        </div>
    )
}