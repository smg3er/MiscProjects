from fastmcp import FastMCP
import psutil
import platform

# Инициализация сервера
mcp = FastMCP("System Info Server")


@mcp.tool()
def get_cpu_info() -> str:
    """
    Получить информацию о процессоре.

    Returns:
        Модель CPU и количество ядер.
    """
    cpu_brand = platform.processor() or "Unknown"
    cpu_cores = psutil.cpu_count(logical=False) or "Unknown"
    cpu_threads = psutil.cpu_count(logical=True) or "Unknown"

    return (
        f"Модель CPU: {cpu_brand}\n"
        f"Физические ядра: {cpu_cores}\n"
        f"Логические ядра (потоки): {cpu_threads}"
    )


@mcp.tool()
def get_memory_info() -> str:
    """
    Получить информацию об оперативной памяти.

    Returns:
        Общий и доступный объем RAM в ГБ.
    """
    memory = psutil.virtual_memory()
    total_gb = round(memory.total / (1024 ** 3), 2)
    available_gb = round(memory.available / (1024 ** 3), 2)

    return (
        f"Всего RAM: {total_gb} ГБ\n"
        f"Доступно RAM: {available_gb} ГБ\n"
        f"Использовано: {memory.percent}%"
    )


@mcp.tool()
def get_system_info() -> str:
    """
    Получить общую информацию о системе.

    Returns:
        ОС, архитектура и общая сводка.
    """
    return (
        f"ОС: {platform.system()} {platform.release()}\n"
        f"Архитектура: {platform.machine()}\n"
        f"Python: {platform.python_version()}"
    )


# Точка входа для запуска сервера
if __name__ == "__main__":
    # Запуск через STDIO (стандартный транспорт для MCP)
    mcp.run()