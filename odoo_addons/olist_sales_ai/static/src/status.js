/** @odoo-module **/
import { Component, onMounted, onWillUnmount, xml } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

class FollowupStatus extends Component {
    static props = { ...standardFieldProps };
    static template = xml`<span class="badge text-bg-info" t-esc="label"/>`;
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.active = true;
        onMounted(() => { this.timer = setInterval(() => this.poll(), 3000); });
        onWillUnmount(() => { this.active = false; clearInterval(this.timer); });
    }
    get label() {
        return { pending: "Đang phân tích", ready: "Chờ duyệt", approved: "Đã giao việc", failed: "Chưa hoàn tất", cancelled: "Đã bỏ qua", checked: "Đã kiểm tra quy tắc", explained: "Đã diễn giải", prepared: "Đã lọc theo Odoo", ranked: "Đã nhận xếp hạng" }[this.props.record.data[this.props.name]] || "";
    }
    async poll() {
        if (!this.active || this.busy || this.props.record.data[this.props.name] !== "pending") return;
        this.busy = true;
        try {
            const state = await this.orm.call(this.props.record.resModel, "poll_state", [[this.props.record.resId]]);
            if (this.active && state !== "pending") await this.action.doAction({ type: "ir.actions.client", tag: "reload" });
        } catch { /* Keep the same proposal and allow an explicit refresh after reconnection. */ }
        finally { this.busy = false; }
    }
}
registry.category("fields").add("olist_ai_status", { component: FollowupStatus, supportedTypes: ["selection"] });
