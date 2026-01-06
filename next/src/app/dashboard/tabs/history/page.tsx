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
import { LucideCopy } from "lucide-react";
import { useStoreContext } from "../../store";
import { notify } from "@/lib/notify";

const retrieve_limit = 10;

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

const statusIcon = (status: string) => {
    switch (status) {
        case 'pass':
            return "✅"
        case 'fail':
            return "❌"
        case 'missing':
            return "⚠️"
        case 'n/a':
            return "❓"
        default:
            return "❔"
    }
}


// # 🚀🛸🪐🌌⭐🌠👽🤖☀️🌙🌧️⚡🌊🌸🍂🌈🔧🛠️⚙️🪓🪛🧰✈️🚁🚗🚲⛵🏍️🛶✅❌⚠️✖➡️⬆️🔁🎨🎸🎮🕹️🐉🧩🕯️📖
const JobRow = ({ job, onClick }: { job: any, onClick?: () => void }) => {
    // let icon = "✅"
    // if (job.status === 'fail') icon = "❌"
    // // else if (job.status === 'pass') icon = "✅"
    // else if (job.status === 'missing') icon = "⚠️"
    // else if (job.status === 'n/a') icon = "❓"
    const icon = statusIcon(job.status)

    return (
        <tr onClick={onClick} className="border-b cursor-pointer hover:bg-gray-50">
            <td className="text-center">{icon}</td>
            <td className="text-left">{job.id}</td>
            {/* <td className="text-left">{job.status}</td> */}
            {/* <td className="text-left">{job.meter_id}</td> */}

            <td className="text-left">{job.hostname}</td>
            <td className="text-left">{job.name}</td>
            {/* <td className="text-left">📖</td> */}
            <td className="text-left">{new Date(job.created_at).toLocaleString()}</td>
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

const JobDialog = ({ job }: { job: any }) => {
    const { systemState, systemDispatch } = useStoreContext()
    const isHandsome = systemState.handsome
    const icon = statusIcon(job.status)
    return (
        <>
            <DialogContent className="min-w-[85vw] ">
                <DialogHeader className="gap-0 space-y-0 m-0 p-0 border-0">
                    <DialogTitle>Job Details — {job?.hostname} — {job?.name} — {job?.status}{icon}</DialogTitle>
                    <DialogDescription>
                        {job?.created_at}
                    </DialogDescription>
                </DialogHeader>

                <ScrollArea className="mt-2 max-h-80 overflow-y-auto w-full rounded-md border border-border px-2 mr-2">
                    <Accordion type="single" collapsible>
                        { job?.data?.kwargs &&
                            <AccordionItem value="kwargs">
                                <AccordionTrigger>program parameters(kwargs)</AccordionTrigger>
                                <AccordionContent>
                                    {isHandsome && <Copyable text={JSON.stringify(job?.data?.kwargs, null, 2)} />}
                                    <pre className="bg-gray-100 rounded-md">
                                        {JSON.stringify(job?.data?.kwargs, null, 2)}
                                    </pre>
                                </AccordionContent>
                            </AccordionItem>
                        }
                        { job?.data?.results &&
                            <AccordionItem value="results">
                                <AccordionTrigger>results</AccordionTrigger>
                                <AccordionContent>
                                    {isHandsome && <Copyable text={JSON.stringify(job?.data?.results, null, 2)} />}
                                    <pre className="bg-gray-100 rounded-md p-2">
                                        {JSON.stringify(job?.data?.results, null, 2)}
                                    </pre>
                                </AccordionContent>
                            </AccordionItem>
                        }
                        { job?.jctl &&
                            <AccordionItem value="journalctl">
                                <AccordionTrigger>journalctl</AccordionTrigger>
                                <AccordionContent>
                                    {isHandsome && <Copyable text={job?.jctl} />}
                                    {/* <pre className="bg-gray-100 rounded-md">
                                        {JSON.stringify(job?.jctl, null, 2)}
                                    </pre> */}
                                    <div className="bg-gray-100 rounded-md p-2">
                                        {job?.jctl}
                                    </div>
                                </AccordionContent>
                            </AccordionItem>
                        }
                    </Accordion>
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
        <div className="p-4">
            {/* <div className="w-full max-w-2xl max-h-96 overflow-y-auto rounded-md bg-red-100 px-4"> */}
            <div className="w-full max-h-100 overflow-y-auto rounded-md border border-border">
                <table className="w-full table-auto border-collapse">
                    <thead className="bg-gray-100 sticky top-0">
                        <tr>
                            <th className="text-left"></th>
                            <th className="text-left">ID</th>
                            {/* <th className="text-left">Status</th> */}
                            {/* <th className="text-left">Meter ID</th> */}
                            <th className="text-left">Meter</th>
                            <th className="text-left">Job</th>
                            {/* <th className="text-left cursor-pointer">Data</th> */}
                            <th className="text-left">Finished</th>
                        </tr>
                    </thead>
                    <tbody>
                        {jobs.map(job => <JobRow key={job.id} job={job} onClick={() => openJobDialog(job)} />)}
                    </tbody>
                </table>
                <div className="flex justify-center my-4">
                    <Button variant={"secondary"} onClick={fetchJobs} className="w-fit">load 10 more</Button>
                </div>
            </div>
            <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
                <JobDialog job={selected} />
            </Dialog>
        </div>
    )
}