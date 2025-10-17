import { Dash } from "./dash/dash"
import { StoreProvider } from "./store"
export default () => {
    return (
        <StoreProvider>
            <div className="border border-[#ff0000]/10 border-1 w-[1920px] h-[1080px] z-999999 overflow-hidden ">
                {/* <button onClick={() => fetch('/flask/system/test').then(res => res.text()).then(text => console.log(text))}>press</button> */}
                <Dash/>
            </div>
        </StoreProvider>

    )
}