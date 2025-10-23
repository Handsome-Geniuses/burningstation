
export default async({ searchParams }: { searchParams: { [key: string]: string | string[] | undefined } }) => {
    const params = await searchParams
    const isHandsome = params.handsome !== undefined
    return (
        <div className="w-screen h-screen bg-neutral-200 overflow-hidden flex items-center justify-center">
            <div className="relative w-[1920px] h-[1080px]">
                <iframe
                    src={`/station${isHandsome?'?handsome':''}`}
                    className="w-full h-full"
                    title="."
                />
            </div>
        </div>
    )
}

