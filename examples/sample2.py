async def flow():
    a = AG1.src()
    xs = await AG1.op(param1=a, param2=42)
    crossing_info = None
    for x in xs:
        AG3.proc(x)
        crossed = await AG4.op2(x)
        if not crossed:
            continue
        approx_time = await AG3.op(x)
        data = await AG4.op(approx_time)
        lat = data["sensor_lat"]
        lon = data["sensor_lon"]
        AG4.proc(approx_time)
        crossing_info = {
            "approx_time": approx_time,
            "details": await AG5.op3(approx_time),
            "item": x,
            "lat": lat,
            "lon": lon,
        }
    return crossing_info